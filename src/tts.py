"""Step 2 - voice-over with edge-tts (free) + word timings for captions."""
import asyncio
import subprocess
from pathlib import Path

from .config import Config
from .util import log, retry

TICKS = 10_000_000  # edge-tts offsets are in 100-nanosecond units


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


async def _synth(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    import edge_tts  # imported lazily so offline tests don't need it

    try:
        comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # older edge-tts emits word boundaries by default
        comm = edge_tts.Communicate(text, voice, rate=rate)
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
def synthesize(cfg: Config, text: str, out: Path) -> tuple[float, list[dict]]:
    words = asyncio.run(_synth(text, cfg.tts_voice, cfg.tts_rate, out))
    duration = probe_duration(out)
    if not words:
        log.warning("No word timings from TTS; using even split for captions")
        words = _even_timings(text, duration)
    log.info("Voice-over: %.1fs, %d words", duration, len(words))
    return duration, words
