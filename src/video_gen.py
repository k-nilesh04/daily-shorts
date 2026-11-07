"""Generate story-matched video scenes with Gemini Omni Flash."""
import base64
import math
import re
import time
from pathlib import Path

from google import genai
from google.genai import errors, types

from .config import Config
from .util import log

MODEL = "gemini-omni-1.2-flash"
MAX_CLIP_SECONDS = 15
ESTIMATED_USD_PER_SECOND_720P = 0.07
RESOLUTION = "720p"
MAX_RATE_LIMIT_RETRIES = 3
RATE_LIMIT_RETRY_DELAY_SECONDS = 30


def _retry_after_seconds(error: errors.APIError) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    retry_after = headers.get("Retry-After") if headers else None
    if retry_after:
        try:
            delay = float(retry_after)
            if math.isfinite(delay):
                return max(0.0, delay)
        except (TypeError, ValueError):
            pass

    details = getattr(error, "details", None)
    error_details = details.get("error", {}) if isinstance(details, dict) else {}
    if not isinstance(error_details, dict):
        return None
    for detail in error_details.get("details", []):
        if not isinstance(detail, dict):
            continue
        if detail.get("@type", "").endswith("google.rpc.RetryInfo"):
            retry_delay = detail.get("retryDelay")
            if not isinstance(retry_delay, str):
                continue
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", retry_delay)
            if match:
                return float(match.group(1))
    return None


def estimate_cost_usd(scene_count: int) -> float:
    return scene_count * MAX_CLIP_SECONDS * ESTIMATED_USD_PER_SECOND_720P


def _generate_one(cfg: Config, prompt: str, dest: Path, scene_number: int) -> Path:
    client = genai.Client(
        api_key=cfg.ai_video_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    try:
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                interaction = client.interactions.create(
                    model=MODEL,
                    input=(
                        f"Create one 15-second cinematic documentary video, portrait orientation. "
                        f"Visual brief: {prompt.strip()} "
                        "Make the action visually engaging and suitable for a Hindi/Hinglish story. "
                        "Generate silent video with no dialogue, narration, text, subtitles, logos, or watermark."
                    ),
                    response_format={
                        "type": "video",
                        "aspect_ratio": "9:16",
                        "resolution": RESOLUTION,
                    },
                    timeout=900,
                )
                break
            except errors.APIError as error:
                if error.code != 429:
                    raise
                if attempt == MAX_RATE_LIMIT_RETRIES:
                    raise RuntimeError(
                        f"Gemini video generation for scene {scene_number} was rate-limited "
                        f"after {attempt + 1} attempts (HTTP 429: {error.message}). "
                        "Check the project's Gemini "
                        "Omni rate limits, usage tier, and billing in AI Studio."
                    ) from error
                wait = RATE_LIMIT_RETRY_DELAY_SECONDS * (2 ** attempt)
                retry_after = _retry_after_seconds(error)
                if retry_after is not None:
                    wait = max(wait, retry_after)
                log.warning(
                    "Scene %d rate-limited by Gemini (HTTP 429). Retry %d/%d in %.1fs",
                    scene_number, attempt + 1, MAX_RATE_LIMIT_RETRIES, wait,
                )
                time.sleep(wait)
    finally:
        client.close()

    video = getattr(interaction, "output_video", None)
    encoded = getattr(video, "data", None)
    if not encoded:
        raise RuntimeError(f"Gemini returned no video for scene {scene_number}")

    try:
        video_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise RuntimeError(f"Gemini returned invalid video data for scene {scene_number}") from error
    if not video_bytes:
        raise RuntimeError(f"Gemini returned an empty video for scene {scene_number}")

    dest.write_bytes(video_bytes)
    log.info("Generated AI scene %d: %s", scene_number, dest.name)
    return dest


def generate_scenes(cfg: Config, prompts: list[str], work: Path) -> list[Path]:
    """Generate scenes sequentially after a fail-closed cost check."""
    expected_count = math.ceil(cfg.target_seconds / MAX_CLIP_SECONDS)
    if not 30 <= cfg.target_seconds <= 60:
        raise ValueError("TARGET_SECONDS must be between 30 and 60")
    if len(prompts) != expected_count:
        raise ValueError(
            f"Expected {expected_count} AI scene prompts for a {cfg.target_seconds}-second video")
    if not cfg.ai_video_key:
        raise RuntimeError("OMNI_API_KEY (or GEMINI_API_KEY) is required for AI video generation")

    estimate = estimate_cost_usd(len(prompts))
    if cfg.ai_video_max_usd <= 0 or estimate > cfg.ai_video_max_usd:
        raise RuntimeError(
            f"Refusing paid AI video generation: estimated video cost is about "
            f"${estimate:.2f} at 720p for {len(prompts)} clips, but "
            f"AI_VIDEO_MAX_USD is ${cfg.ai_video_max_usd:.2f}. "
            "This is a preflight estimate, not a provider-enforced billing cap. "
            "Increase the limit only after reviewing current Gemini pricing.")

    work.mkdir(parents=True, exist_ok=True)
    log.info("Generating %d AI scenes sequentially at 720p (estimated video cost: $%.2f)",
             len(prompts), estimate)
    paths = [work / f"scene_{index:02d}.mp4" for index in range(1, len(prompts) + 1)]
    return [
        _generate_one(cfg, prompt, path, index)
        for index, (prompt, path) in enumerate(zip(prompts, paths), start=1)
    ]
