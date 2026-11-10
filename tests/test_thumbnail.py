import os

os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import Config
from src.thumbnail import THUMBNAIL_HEIGHT, THUMBNAIL_WIDTH, _build_prompt, generate


class PromptTests(unittest.TestCase):
    def test_prompt_includes_title_and_synopsis(self):
        prompt = _build_prompt(
            "Funny Cat Video", "A cat tries to cook pasta and fails spectacularly."
        )
        self.assertIn("Funny Cat Video", prompt)
        self.assertIn("A cat tries to cook pasta", prompt)
        self.assertIn("1280x720", prompt)
        self.assertIn("3D cartoon", prompt)

    def test_prompt_truncates_long_script(self):
        long_script = "word " * 200
        prompt = _build_prompt("Title", long_script)
        self.assertLess(len(prompt), 1000)


class GenerateTests(unittest.TestCase):
    def test_returns_none_without_api_key(self):
        cfg = Config(gemini_key="", thumbnail_model="test-model")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate(cfg, "Title", "Script", Path(temp_dir) / "thumb.jpg")
        self.assertIsNone(result)

    @patch("src.thumbnail.genai.Client")
    def test_returns_none_on_api_error(self, client_factory):
        from google.genai import errors

        client = client_factory.return_value
        client.models.generate_content.side_effect = errors.ClientError(
            400, {"error": {"message": "bad request", "status": "INVALID_ARGUMENT"}}
        )
        cfg = Config(gemini_key="test-key", thumbnail_model="test-model")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate(cfg, "Title", "Script", Path(temp_dir) / "thumb.jpg")
        self.assertIsNone(result)

    @patch("src.thumbnail.genai.Client")
    def test_returns_none_when_no_image_in_response(self, client_factory):
        client = client_factory.return_value
        response = MagicMock()
        response.candidates = [MagicMock(content=MagicMock(parts=[]))]
        client.models.generate_content.return_value = response
        cfg = Config(gemini_key="test-key", thumbnail_model="test-model")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate(cfg, "Title", "Script", Path(temp_dir) / "thumb.jpg")
        self.assertIsNone(result)

    @patch("src.thumbnail.genai.Client")
    def test_saves_image_with_pillow(self, client_factory):
        import io

        from PIL import Image

        img = Image.new("RGB", (640, 480), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()

        part = MagicMock()
        part.inline_data.data = raw
        part.inline_data.mime_type = "image/png"
        content = MagicMock(parts=[part])
        candidate = MagicMock(content=content)
        response = MagicMock(candidates=[candidate])
        client = client_factory.return_value
        client.models.generate_content.return_value = response

        cfg = Config(gemini_key="test-key", thumbnail_model="test-model")
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "thumb.jpg"
            result = generate(cfg, "Title", "Script", out)
            self.assertEqual(result, out)
            self.assertTrue(out.is_file())
            with Image.open(out) as saved:
                self.assertEqual(saved.size, (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT))

    @patch("src.thumbnail.genai.Client")
    def test_uses_configured_model(self, client_factory):
        client = client_factory.return_value
        response = MagicMock(candidates=[])
        client.models.generate_content.return_value = response
        cfg = Config(gemini_key="test-key", thumbnail_model="custom-thumb-model")
        with tempfile.TemporaryDirectory() as temp_dir:
            generate(cfg, "Title", "Script", Path(temp_dir) / "thumb.jpg")
        call = client.models.generate_content.call_args
        self.assertEqual(call.kwargs["model"], "custom-thumb-model")

    @patch("src.thumbnail.genai.Client")
    def test_uses_default_model_when_not_configured(self, client_factory):
        client = client_factory.return_value
        response = MagicMock(candidates=[])
        client.models.generate_content.return_value = response
        cfg = Config(gemini_key="test-key", thumbnail_model="")
        with tempfile.TemporaryDirectory() as temp_dir:
            generate(cfg, "Title", "Script", Path(temp_dir) / "thumb.jpg")
        call = client.models.generate_content.call_args
        self.assertEqual(call.kwargs["model"], "gemini-2.0-flash-exp")


if __name__ == "__main__":
    unittest.main()
