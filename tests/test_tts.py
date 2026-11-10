import os

os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.config import Config
from src.tts import _even_timings, probe_duration, synthesize


class ProbeDurationTests(unittest.TestCase):
    @patch("src.tts.subprocess.run")
    def test_reads_duration(self, run):
        run.return_value = SimpleNamespace(stdout="12.5\n")
        self.assertEqual(probe_duration(Path("voice.mp3")), 12.5)

    @patch("src.tts.subprocess.run")
    def test_reports_ffprobe_failure(self, run):
        run.side_effect = subprocess.CalledProcessError(1, ["ffprobe"], stderr="invalid data")
        with self.assertRaisesRegex(RuntimeError, "could not read.*invalid data"):
            probe_duration(Path("voice.mp3"))

    @patch("src.tts.subprocess.run")
    def test_reports_missing_ffprobe(self, run):
        run.side_effect = FileNotFoundError()
        with self.assertRaisesRegex(RuntimeError, "ffprobe was not found"):
            probe_duration(Path("voice.mp3"))

    @patch("src.tts.subprocess.run")
    def test_reports_unparseable_duration(self, run):
        run.return_value = SimpleNamespace(stdout="")
        with self.assertRaisesRegex(RuntimeError, "no usable duration"):
            probe_duration(Path("voice.mp3"))


class SynthesisTests(unittest.TestCase):
    @patch("src.util.time.sleep")
    @patch("src.tts.asyncio.run", return_value=[])
    def test_empty_audio_is_reported(self, _run, _sleep):
        with tempfile.TemporaryDirectory() as temp_dir:
            voice = Path(temp_dir) / "voice.mp3"
            voice.write_bytes(b"")
            cfg = Config(tts_voice="hi-IN-MadhurNeural")
            with self.assertRaisesRegex(RuntimeError, "produced no audio"):
                synthesize(cfg, "hello there", voice)

    def test_even_timings_fill_the_duration(self):
        words = _even_timings("one two three four", 8.0)
        self.assertEqual(len(words), 4)
        self.assertAlmostEqual(words[0]["start"], 0.0)
        self.assertAlmostEqual(words[-1]["end"], 8.0)
        for previous, current in zip(words, words[1:]):
            self.assertAlmostEqual(previous["end"], current["start"])


if __name__ == "__main__":
    unittest.main()
