"""Step 4 - assemble the final 1080x1920 MP4 with FFmpeg."""
import math
import subprocess
from pathlib import Path

from .captions import write_ass
from .config import Config
from .util import log


def run(cmd: list[str], cwd: Path | None = None) -> None:
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        log.error("FFmpeg failed:\n%s", res.stderr[-2500:])
        raise RuntimeError("ffmpeg failed")


def segments_needed(cfg: Config, duration: float, has_hook: bool) -> int:
    body = duration - (cfg.omni_hook_seconds if has_hook else 0)
    return max(1, math.ceil(body / cfg.segment_seconds))


def _normalize(cfg: Config, src: Path, dst: Path, seconds: float) -> None:
    """Crop/scale to 9:16, constant fps, no audio, exact length (loops short clips)."""
    vf = (f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=increase,"
          f"crop={cfg.width}:{cfg.height},setsar=1,fps={cfg.fps},format=yuv420p")
    run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(src),
         "-t", f"{seconds:.3f}", "-vf", vf, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(dst)])


def build(cfg: Config, clips: list[Path], hook: Path | None, voice: Path,
          duration: float, words: list[dict], out: Path, work: Path) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    plan: list[tuple[Path, float]] = []
    remaining = duration

    if hook:
        h = min(cfg.omni_hook_seconds, duration * 0.4)
        plan.append((hook, h))
        remaining -= h

    n = len(clips)
    per = max(1.5, remaining / n) if n else remaining
    for i, c in enumerate(clips):
        if remaining <= 0.05:
            break
        d = remaining if i == n - 1 else min(per, remaining)
        plan.append((c, d))
        remaining -= d

    parts = []
    for i, (src, secs) in enumerate(plan):
        dst = work / f"seg_{i:02d}.mp4"
        _normalize(cfg, src, dst, secs)
        parts.append(dst)

    concat_list = work / "concat.txt"
    concat_list.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    visual = work / "visual.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", "concat.txt", "-c", "copy", "visual.mp4"], cwd=work)

    write_ass(cfg, words, work / "captions.ass")
    out.parent.mkdir(parents=True, exist_ok=True)
    # run inside `work` so the ass path needs no escaping
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", "visual.mp4", "-i", str(voice.resolve()),
         "-vf", "ass=captions.ass", "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
         str(out.resolve())], cwd=work)
    log.info("Rendered %s (%.1f MB)", out.name, out.stat().st_size / 1e6)
    return out
