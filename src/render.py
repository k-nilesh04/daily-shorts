"""Step 4 - assemble the final 1080x1920 MP4 with FFmpeg."""

import subprocess
from pathlib import Path

from .captions import write_ass
from .config import Config
from .util import log


def run(cmd: list[str], cwd: Path | None = None) -> None:
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise RuntimeError(
            "ffmpeg was not found; install FFmpeg and add it to PATH "
            "(https://ffmpeg.org/download.html)"
        ) from error
    if res.returncode != 0:
        log.error("FFmpeg failed:\n%s", res.stderr[-2500:])
        raise RuntimeError(f"ffmpeg failed ({' '.join(cmd)})")


def _normalize_filter(cfg: Config) -> str:
    """FFmpeg filter that pins the output size and frame rate."""
    if cfg.layout == "frame":
        size = cfg.frame_size
        overscan = int(size * 1.08)
        return (
            f"scale={overscan}:{overscan}:force_original_aspect_ratio=increase,"
            f"crop={overscan}:{overscan},"
            f"zoompan=z='min(zoom+0.00035,1.08)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={size}x{size}:fps={cfg.fps},setsar=1,format=yuv420p"
        )
    # Fullscreen 9:16 vertical video (1080x1920) at the configured frame rate.
    return (
        f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=increase,"
        f"crop={cfg.width}:{cfg.height},"
        f"fps={cfg.fps},setsar=1,format=yuv420p"
    )


def _normalize(cfg: Config, src: Path, dst: Path, seconds: float) -> None:
    """Scale and crop each source clip to exact length, resolution, and fps."""
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-stream_loop",
            "-1",
            "-i",
            str(src),
            "-t",
            f"{seconds:.3f}",
            "-vf",
            _normalize_filter(cfg),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            str(dst),
        ]
    )


def _presentation_filter(cfg: Config, duration: float) -> str:
    x, y, size = cfg.frame_x, cfg.frame_y, cfg.frame_size
    border = 8
    edge = 56
    progress_y = cfg.height - 100
    progress_width = max(1, size - 2 * border)
    progress_slope = (progress_width - 1) / max(duration, 0.01)
    scan_y = f"'{y}+mod(t*28,{size})'"
    return (
        f"[1:v]scale={size}:{size}:force_original_aspect_ratio=increase,"
        f"crop={size}:{size},setsar=1,format=yuv420p[square];"
        f"[0:v][square]overlay=(W-w)/2:(H-h)/2:shortest=1,"
        f"drawbox=x={x - border}:y={y - border}:w={size + 2 * border}:"
        f"h={size + 2 * border}:color=0x00d7ff@0.72:t=2,"
        f"drawbox=x={x - border}:y={y - border}:w={edge}:h=4:"
        f"color=0x00d7ff@1:t=fill,"
        f"drawbox=x={x - border}:y={y - border}:w=4:h={edge}:"
        f"color=0x00d7ff@1:t=fill,"
        f"drawbox=x={x + size + border - edge}:y={y - border}:w={edge}:h=4:"
        f"color=0x00d7ff@1:t=fill,"
        f"drawbox=x={x + size + border - 4}:y={y - border}:w=4:h={edge}:"
        f"color=0x00d7ff@1:t=fill,"
        f"drawbox=x={x - border}:y={y + size + border - 4}:w={edge}:h=4:"
        f"color=0x00d7ff@1:t=fill,"
        f"drawbox=x={x - border}:y={y + size + border - edge}:w=4:h={edge}:"
        f"color=0x00d7ff@1:t=fill,"
        f"drawbox=x={x + size + border - edge}:y={y + size + border - 4}:"
        f"w={edge}:h=4:color=0x00d7ff@1:t=fill,"
        f"drawbox=x={x + size + border - 4}:y={y + size + border - edge}:"
        f"w=4:h={edge}:color=0x00d7ff@1:t=fill,"
        f"drawbox=x={x}:y={scan_y}:w={size}:h=2:color=0x00d7ff@0.18:t=fill,"
        f"drawbox=x={x}:y={progress_y}:w={progress_width}:h=3:"
        f"color=0x606060@0.75:t=fill,"
        f"drawbox=x={x}:y={progress_y}:w='1+{progress_slope:.6f}*t':h=3:"
        f"color=0x00d7ff@1:t=fill,"
        f"ass=captions.ass[vout]"
    )


def build(
    cfg: Config,
    clips: list[Path],
    voice: Path,
    duration: float,
    words: list[dict],
    out: Path,
    work: Path,
) -> Path:
    if not clips:
        raise ValueError("render.build needs at least one video clip")
    if duration <= 0:
        raise ValueError(f"render.build needs a positive narration duration, got {duration!r}")
    work.mkdir(parents=True, exist_ok=True)
    plan: list[tuple[Path, float]] = []
    remaining = duration

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
    run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            "concat.txt",
            "-c",
            "copy",
            "visual.mp4",
        ],
        cwd=work,
    )

    write_ass(cfg, words, work / "captions.ass")
    out.parent.mkdir(parents=True, exist_ok=True)
    layout = getattr(cfg, "layout", "fullscreen")
    if layout == "frame":
        run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c=black:s={cfg.width}x{cfg.height}:r={cfg.fps}:d={duration:.3f}",
                "-i",
                "visual.mp4",
                "-i",
                str(voice.resolve()),
                "-filter_complex",
                _presentation_filter(cfg, duration),
                "-map",
                "[vout]",
                "-map",
                "2:a",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(out.resolve()),
            ],
            cwd=work,
        )
    else:
        # Fullscreen 9:16 layout with burned-in animated subtitles
        run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                "visual.mp4",
                "-i",
                str(voice.resolve()),
                "-vf",
                "ass=captions.ass",
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-shortest",
                "-movflags",
                "+faststart",
                str(out.resolve()),
            ],
            cwd=work,
        )
    log.info("Rendered %s (%.1f MB)", out.name, out.stat().st_size / 1e6)
    return out
