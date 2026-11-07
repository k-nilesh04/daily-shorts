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
            # one landscape clip and one SHORT portrait AI-scene clip (forces loop path)
            ff("-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24:duration=6", "-pix_fmt", "yuv420p", str(d / "a.mp4"))
            ff("-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=25:duration=2", "-pix_fmt", "yuv420p", str(d / "b.mp4"))
            dur = probe_duration(d / "voice.mp3")
            words = _even_timings("Honey never spoils because it is low in water and acidic " * 2, dur)

            out = d / "video.mp4"
            clips = [d / "a.mp4", d / "b.mp4"]
            render.build(cfg, clips, d / "voice.mp3", dur, words, out, d / "r")

            self.assertTrue(out.exists())
            info = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=p=0", str(out)],
                capture_output=True, text=True, check=True).stdout.strip()
            self.assertEqual(info, "1080,1920")
            self.assertAlmostEqual(probe_duration(out), dur, delta=0.6)

            def pixel(x, y):
                return subprocess.run(
                    ["ffmpeg", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1",
                     "-vf", f"crop=1:1:{x}:{y},format=rgb24", "-f", "rawvideo", "-"],
                    capture_output=True, check=True).stdout

            self.assertEqual(pixel(10, 10), b"\x00\x00\x00")
            self.assertNotEqual(pixel(540, 960), b"\x00\x00\x00")

class RenderDesignTests(unittest.TestCase):
    def test_square_frame_layout_and_motion_overlays(self):
        cfg = config.load()
        self.assertEqual(cfg.frame_size, 900)
        self.assertEqual((cfg.frame_x, cfg.frame_y), (90, 510))
        filters = render._presentation_filter(cfg, 45)
        self.assertIn("overlay=(W-w)/2:(H-h)/2", filters)
        self.assertIn("mod(t*28,900)", filters)
        self.assertIn("drawbox=", filters)
        self.assertIn("ass=captions.ass", filters)

    def test_captions_have_karaoke_and_pop_animation(self):
        cfg = config.load()
        words = [
            {"text": "Watch", "start": 0.0, "end": 0.3},
            {"text": "this", "start": 0.3, "end": 0.55},
            {"text": "carefully.", "start": 0.55, "end": 1.0},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = captions.write_ass(cfg, words, Path(d) / "captions.ass")
            content = path.read_text(encoding="utf-8")
        self.assertIn(r"\kf30", content)
        self.assertIn(r"\t(0,130,\fscx100\fscy100)", content)
        self.assertIn("FIELD NOTES", content)
        self.assertIn(r"\pos(540,1580)", content)


if __name__ == "__main__":
    unittest.main()
