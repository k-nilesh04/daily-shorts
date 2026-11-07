"""OPTIONAL hook clip for the first seconds of the video.

Two sources, in order:
  1. hooks/*.mp4   - clips YOU made by hand (e.g. free in Google Flow / YouTube
                     Shorts). Costs nothing. Used whenever USE_OMNI is false
                     and the folder is not empty.
  2. Gemini Omni API (paid, preview) - only when USE_OMNI=true and OMNI_API_KEY set.

Every failure returns None so the pipeline falls back to stock footage.
"""
import random
import time
from pathlib import Path

from .config import Config
from .util import log

OMNI_MODEL = "gemini-omni-flash-preview"


def _local_hook(cfg: Config) -> Path | None:
    clips = sorted(cfg.hooks_dir.glob("*.mp4"))
    return random.choice(clips) if clips else None


def _omni_generate(cfg: Config, prompt: str, out: Path) -> Path:
    """Call Gemini Omni Flash (preview).

    NOTE: written from public docs/blog examples (Interactions API). The response
    shape of a preview API may differ - if so this raises and we fall back to
    stock footage. Verify against Google's current docs before enabling.
    """
    from google import genai

    client = genai.Client(api_key=cfg.omni_key)
    interaction = client.interactions.create(
        model=OMNI_MODEL,
        input=f"{prompt}. Vertical 9:16 video, {int(cfg.omni_hook_seconds)} seconds, no on-screen text.",
    )
    # Video generation is asynchronous: poll until finished.
    for _ in range(60):
        status = getattr(interaction, "status", None)
        if status in (None, "completed", "succeeded", "done"):
            break
        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"Omni interaction ended with status {status}")
        time.sleep(10)
        interaction = client.interactions.get(interaction.id)

    video_bytes = None
    for out_item in getattr(interaction, "outputs", None) or []:
        data = getattr(out_item, "data", None) or getattr(getattr(out_item, "video", None), "data", None)
        if data:
            video_bytes = data
            break
    if not video_bytes:
        raise RuntimeError("Could not find video bytes in Omni response (API shape changed?)")
    out.write_bytes(video_bytes)
    return out


def get_hook(cfg: Config, hook_prompt: str, work: Path) -> Path | None:
    if cfg.use_omni and cfg.omni_key:
        try:
            path = _omni_generate(cfg, hook_prompt, work / "omni_hook.mp4")
            log.info("Using Omni hook clip")
            return path
        except Exception as e:  # noqa: BLE001 - must never break the daily run
            log.warning("Omni failed, falling back: %s", e)
    local = _local_hook(cfg)
    if local:
        log.info("Using local hook clip %s", local.name)
    return local
