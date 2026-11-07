"""Offline smoke test: no API keys or internet needed, only FFmpeg.
Run:  python -m unittest discover -s tests -v
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src import captions, config, render
from src.tts import _even_timings, probe_duration


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class OfflinePipeline(unittest.TestCase):
    def test_group_words_and_timestamps(self):
        words = [{"text": t, "start": i * 0.4, "end": i * 0.4 + 0.35}
                 for i, t in enumerate("Did you know? Honey never spoils at all".split())]
        groups = captions.group_words(words)
        self.assertEqual(groups[0]["text"], "Did you know?")
        self.assertEqual(captions._ts(3725.456), "1:02:05.46")

    def test_end_to_end_render(self):
        cfg = config.load()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            ff("-f", "lavfi", "-i", "sine=frequency=220:duration=12", str(d / "voice.mp3"))
            # one landscape clip, one SHORT portrait clip (forces loop path), one hook
            ff("-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24:duration=6", "-pix_fmt", "yuv420p", str(d / "a.mp4"))
            ff("-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=25:duration=2", "-pix_fmt", "yuv420p", str(d / "b.mp4"))
            ff("-f", "lavfi", "-i", "smptebars=size=1080x1920:rate=30:duration=6", "-pix_fmt", "yuv420p", str(d / "hook.mp4"))
            dur = probe_duration(d / "voice.mp3")
            words = _even_timings("Honey never spoils because it is low in water and acidic " * 2, dur)

            out = d / "video.mp4"
            need = render.segments_needed(cfg, dur, True)
            clips = ([d / "a.mp4", d / "b.mp4"] * 5)[:need]
            render.build(cfg, clips, d / "hook.mp4", d / "voice.mp3", dur, words, out, d / "r")

            self.assertTrue(out.exists())
            info = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=p=0", str(out)],
                capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(info, "1080,1920")
            self.assertAlmostEqual(probe_duration(out), dur, delta=0.6)


if __name__ == "__main__":
    unittest.main()
