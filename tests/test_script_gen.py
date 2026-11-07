import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import types

from src.config import Config
from src.script_gen import _parse, generate


class ScriptGenerationTests(unittest.TestCase):
    @patch("src.script_gen.genai.Client")
    def test_json_generation_uses_v1beta(self, client_factory):
        response_data = {
            "topic": "Ancient Roman Concrete",
            "title": "Why Roman Concrete Lasts",
            "script": "Roman concrete can last for thousands of years.",
            "description": "A fact about Roman concrete.",
            "tags": ["history"],
            "keywords": ["roman concrete"],
            "scene_prompts": [
                "A close view of ancient Roman concrete being mixed.",
                "An ancient Roman harbor structure beside the sea.",
                "Modern scientists studying ancient Roman concrete.",
            ],
        }
        client = client_factory.return_value
        client.models.generate_content.return_value = SimpleNamespace(
            text=json.dumps(response_data))

        result = generate(Config(gemini_key="test-key"), [])

        client_factory.assert_called_once_with(
            api_key="test-key",
            http_options=types.HttpOptions(api_version="v1beta"),
        )
        self.assertEqual(result["topic"], response_data["topic"])

    def test_rejects_scripts_over_duration_word_limit(self):
        response_data = {
            "topic": "Ancient Roman Concrete",
            "title": "Why Roman Concrete Lasts",
            "script": " ".join(["story"] * 91),
            "description": "A fact about Roman concrete.",
            "tags": ["history"],
            "keywords": ["roman concrete"],
            "scene_prompts": ["scene one", "scene two", "scene three"],
        }

        with self.assertRaisesRegex(ValueError, "maximum of 90 words"):
            _parse(json.dumps(response_data), scene_count=3, max_words=90)


if __name__ == "__main__":
    unittest.main()
