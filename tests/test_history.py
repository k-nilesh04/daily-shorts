import json
import tempfile
import unittest
from pathlib import Path

from src.history import HistoryError, append, load, recent_topics


class HistoryTests(unittest.TestCase):
    def test_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(load(Path(temp_dir) / "history.json"), [])

    def test_append_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "data" / "history.json"
            append(path, "topic one", "Title One", "video-1")
            append(path, "topic two", "Title Two", None)

            items = load(path)
            self.assertEqual([item["topic"] for item in items], ["topic one", "topic two"])
            self.assertEqual(items[0]["video_id"], "video-1")
            self.assertIsNone(items[1]["video_id"])
            self.assertFalse(path.with_name("history.json.tmp").exists())

    def test_append_keeps_at_most_500_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            path.write_text(json.dumps([
                {"topic": f"topic {index}", "title": f"Title {index}"}
                for index in range(505)
            ]), encoding="utf-8")

            append(path, "new topic", "New Title", None)

            items = load(path)
            self.assertEqual(len(items), 500)
            self.assertEqual(items[-1]["topic"], "new topic")

    def test_recent_topics_returns_the_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            path.write_text(json.dumps([
                {"topic": "one"}, {"topic": "two"}, {"topic": "three"},
            ]), encoding="utf-8")

            self.assertEqual(recent_topics(path, n=2), ["two", "three"])

    def test_corrupt_json_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(HistoryError, "not valid JSON"):
                load(path)

    def test_non_list_history_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            path.write_text(json.dumps({"topic": "one"}), encoding="utf-8")
            with self.assertRaisesRegex(HistoryError, "must contain a JSON list"):
                load(path)

    def test_non_object_entry_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.json"
            path.write_text(json.dumps(["topic one"]), encoding="utf-8")
            with self.assertRaisesRegex(HistoryError, "entry 0"):
                load(path)


if __name__ == "__main__":
    unittest.main()
