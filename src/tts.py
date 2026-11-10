"""Step 2 - voice-over with edge-tts (free) + word timings for captions."""
import asyncio
import subprocess
from pathlib import Path

from .config import Config
from .util import log, retry

TICKS = 10_000_000  # edge-tts offsets are in 100-nanosecond units


def probe_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "ffprobe was not found; install FFmpeg and add it to PATH "
            "(https://ffmpeg.org/download.html)") from error
    except subprocess.CalledProcessError as error:
        details = (error.stderr or "").strip()
        raise RuntimeError(
            f"ffprobe could not read {path}: {details or 'non-zero exit code'}") from error
    raw = result.stdout.strip()
    try:
        return float(raw)
    except ValueError as error:
        raise RuntimeError(
            f"ffprobe returned no usable duration for {path} (got {raw!r})") from error


async def _synth(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    import edge_tts  # imported lazily so offline tests don't need it
    import re

    # Normalize whitespace and drop control characters that occasionally make
    # the Microsoft TTS endpoint return no audio.
    clean = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        raise RuntimeError("TTS text is empty after cleaning")

    try:
        comm = edge_tts.Communicate(clean, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # older edge-tts emits word boundaries by default
        comm = edge_tts.Communicate(clean, voice, rate=rate)
    words: list[dict] = []
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / TICKS
                words.append({
                    "text": chunk["text"],
                    "start": start,
                    "end": start + chunk["duration"] / TICKS,
                })
    return words


def _even_timings(text: str, duration: float) -> list[dict]:
    """Fallback when the service returns no word boundaries."""
    toks = text.split()
    total = sum(len(t) + 1 for t in toks)
    t, out = 0.0, []
    for tok in toks:
        d = duration * (len(tok) + 1) / total
        out.append({"text": tok, "start": t, "end": t + d})
        t += d
    return out


@retry(times=3, delay=5)
def trim_audio(path: Path, target_seconds: float) -> None:
    """Trim an audio file in place to at most ``target_seconds``."""
    tmp = path.with_name(path.stem + ".trimmed" + path.suffix)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
             "-t", f"{target_seconds:.3f}", "-c:a", "libmp3lame", "-q:a", "4",
             str(tmp)],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError as error:
        raise RuntimeError(
            "ffmpeg was not found; install FFmpeg and add it to PATH "
            "(https://ffmpeg.org/download.html)") from error
    except subprocess.CalledProcessError as error:
        details = (error.stderr or "").strip()
        raise RuntimeError(
            f"Could not trim audio {path.name}: "
            f"{details or 'FFmpeg returned a non-zero exit code'}") from error
    if not tmp.is_file() or tmp.stat().st_size == 0:
        raise RuntimeError(f"ffmpeg produced no trimmed audio for {path.name}")
    tmp.replace(path)


def trim_words(words: list[dict], target_seconds: float) -> list[dict]:
    """Keep only words that end at or before ``target_seconds``."""
    kept = [w for w in words if float(w.get("end", 0)) <= target_seconds + 0.05]
    if kept and float(kept[-1].get("end", 0)) > target_seconds:
        kept[-1]["end"] = target_seconds
    return kept


def normalize_audio(path: Path, target_lufs: float = -14.0) -> None:
    """Normalize audio loudness to target LUFS using FFmpeg loudnorm filter."""
    tmp = path.with_name(path.stem + ".normalized" + path.suffix)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
             "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
             "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "4", str(tmp)],
            capture_output=True, text=True, check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        log.warning("Audio normalization skipped: %s", error)
        return
    if tmp.is_file() and tmp.stat().st_size > 0:
        tmp.replace(path)
        log.info("Audio normalized to %.1f LUFS", target_lufs)
    else:
        tmp.unlink(missing_ok=True)


@retry(times=3, delay=5)
def synthesize(cfg: Config, text: str, out: Path) -> tuple[float, list[dict]]:
    try:
        words = asyncio.run(_synth(text, cfg.tts_voice, cfg.tts_rate, out))
    except Exception as error:  # noqa: BLE001 - edge-tts raises non-RuntimeError types
        # edge-tts raises NoAudioReceived (an Exception, not RuntimeError) when
        # the service returns no audio. Convert to RuntimeError so the adaptive
        # retry loop in main.py can regenerate the script, and so the message is
        # actionable instead of a raw traceback.
        raise RuntimeError(
            f"edge-tts produced no audio for voice {cfg.tts_voice!r} "
            f"(TTS_RATE={cfg.tts_rate!r}): {error}. Check TTS_VOICE and "
            "TTS_RATE, or retry (the Microsoft TTS endpoint is occasionally "
            "flaky)."
        ) from error
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError(
            f"edge-tts produced no audio for voice {cfg.tts_voice!r}; "
            "check TTS_VOICE and TTS_RATE")
    duration = probe_duration(out)
    if not words:
        log.warning("No word timings from TTS; using even split for captions")
        words = _even_timings(text, duration)
    log.info("Voice-over: %.1fs, %d words", duration, len(words))
    return duration, words
