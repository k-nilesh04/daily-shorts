import os

os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.genai import types

from src.config import Config
from src.script_gen import (
    ScriptLengthError,
    _parse,
    _prompt,
    generate,
    word_budget,
)


def payload(**overrides):
    data = {
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
    data.update(overrides)
    return data


class ScriptBudgetTests(unittest.TestCase):
    def test_word_budget_matches_measured_speaking_rate(self):
        min_words, target_words, max_words = word_budget(45)
        # ~2.5 words/second, not the old ~1.3 words/second budget.
        self.assertGreaterEqual(target_words, 80)
        self.assertLessEqual(target_words, 100)
        self.assertLessEqual(min_words, target_words)
        self.assertLessEqual(target_words, max_words)

    def test_budget_never_exceeds_the_short_limit(self):
        for target in (30, 45, 60):
            self.assertLessEqual(word_budget(target)[2], 60 * 2.5)

    def test_prompt_asks_for_realistic_word_count(self):
        prompt = _prompt(Config(gemini_key="test-key", target_seconds=45), [])
        min_words, target_words, max_words = word_budget(45)
        self.assertIn(f"about {target_words} words", prompt)
        self.assertIn(f"between {min_words} and {max_words} words", prompt)
        self.assertNotIn("Pixar", prompt)
        self.assertNotIn("Disney", prompt)


class ScriptParsingTests(unittest.TestCase):
    def test_rejects_scripts_over_duration_word_limit(self):
        with self.assertRaisesRegex(ScriptLengthError, "maximum is 90"):
            _parse(json.dumps(payload(script=" ".join(["story"] * 91))), 3, 90)

    def test_rejects_tags_as_a_string(self):
        with self.assertRaisesRegex(ValueError, "tags"):
            _parse(json.dumps(payload(tags="funny")), 3, 90)

    def test_rejects_non_object_top_level_json(self):
        with self.assertRaisesRegex(ValueError, "must be an object"):
            _parse(json.dumps([payload()]), 3, 90)

    def test_rejects_empty_required_strings(self):
        with self.assertRaisesRegex(ValueError, "script"):
            _parse(json.dumps(payload(script="   ")), 3, 90)
        with self.assertRaisesRegex(ValueError, "title"):
            _parse(json.dumps(payload(title=None)), 3, 90)

    def test_rejects_malformed_json_with_location(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            _parse("{not json", 3, 90)

    def test_rejects_wrong_scene_prompt_count(self):
        with self.assertRaisesRegex(ValueError, "exactly 3"):
            _parse(json.dumps(payload(scene_prompts=["only one"])), 3, 90)

    def test_strips_code_fences_and_hashtags(self):
        fenced = "```json\n" + json.dumps(payload(tags=["#funny"])) + "\n```"
        data = _parse(fenced, 3, 90)
        self.assertEqual(data["tags"], ["funny"])


class ScriptGenerationTests(unittest.TestCase):
    @patch("src.script_gen.genai.Client")
    def test_json_generation_uses_v1beta(self, client_factory):
        client = client_factory.return_value
        client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(payload()))

        result = generate(Config(gemini_key="test-key"), [])

        client_factory.assert_called_once_with(
            api_key="test-key",
            http_options=types.HttpOptions(api_version="v1beta"),
        )
        self.assertEqual(result["topic"], "Ancient Roman Concrete")

    def test_generate_requires_api_key(self):
        with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
            generate(Config(gemini_key=""), [])

    @patch("src.script_gen.genai.Client")
    def test_requests_shorter_rewrite_when_script_exceeds_limit(self, client_factory):
        max_words = word_budget(45)[2]
        overlong = payload(script=" ".join(["story"] * (max_words + 20)))
        short_response = payload(script="A short, engaging story.")
        client = client_factory.return_value
        client.models.generate_content.side_effect = [
            SimpleNamespace(text=json.dumps(overlong)),
            SimpleNamespace(text=json.dumps(short_response)),
        ]

        result = generate(Config(gemini_key="test-key"), [])

        self.assertEqual(result["script"], "A short, engaging story.")
        self.assertEqual(client.models.generate_content.call_count, 2)
        correction_prompt = client.models.generate_content.call_args_list[1].kwargs["contents"]
        self.assertIn(f"previous narration was {max_words + 20} words", correction_prompt)
        self.assertIn(f"hard limit of {max_words}", correction_prompt)

    @patch("src.script_gen.genai.Client")
    def test_auto_trims_script_when_all_attempts_exceed_limit(self, client_factory):
        max_words = word_budget(45)[2]
        overlong = payload(script=" ".join(["story"] * (max_words + 30)))
        client = client_factory.return_value
        client.models.generate_content.return_value = SimpleNamespace(text=json.dumps(overlong))

        result = generate(Config(gemini_key="test-key"), [])

        self.assertLessEqual(len(result["script"].split()), max_words)
        self.assertEqual(client.models.generate_content.call_count, 3)

    @patch("src.script_gen.genai.Client")
    def test_retries_invalid_json_then_succeeds(self, client_factory):
        client = client_factory.return_value
        client.models.generate_content.side_effect = [
            SimpleNamespace(text="{not json"),
            SimpleNamespace(text=json.dumps(payload())),
        ]

        result = generate(Config(gemini_key="test-key"), [])

        self.assertEqual(result["title"], "Why Roman Concrete Lasts")
        self.assertEqual(client.models.generate_content.call_count, 2)
        correction = client.models.generate_content.call_args_list[1].kwargs["contents"]
        self.assertIn("previous response was rejected", correction)

    @patch("src.script_gen.genai.Client")
    def test_invalid_json_after_all_attempts_is_reported(self, client_factory):
        client = client_factory.return_value
        client.models.generate_content.return_value = SimpleNamespace(text="{not json")

        with self.assertRaisesRegex(RuntimeError, "did not return a valid script"):
            generate(Config(gemini_key="test-key"), [])

        self.assertEqual(client.models.generate_content.call_count, 3)

    @patch("src.script_gen.genai.Client")
    def test_empty_model_text_is_reported(self, client_factory):
        client = client_factory.return_value
        client.models.generate_content.return_value = SimpleNamespace(text=None)

        with self.assertRaisesRegex(RuntimeError, "no text content"):
            generate(Config(gemini_key="test-key"), [])


if __name__ == "__main__":
    unittest.main()
