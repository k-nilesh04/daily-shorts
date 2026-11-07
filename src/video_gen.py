"""Generate story-matched video scenes with Gemini Omni Flash."""
import base64
import math
import re
import subprocess
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
MAX_RATE_LIMIT_RETRY_DELAY_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 60
MAX_GENERATION_WAIT_SECONDS = 25 * 60
POLL_INTERVAL_SECONDS = 5


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


def _generate_one(
    cfg: Config, prompt: str, dest: Path, scene_number: int, deadline: float,
) -> Path:
    client = genai.Client(
        api_key=cfg.ai_video_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    try:
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"Gemini video generation exceeded its "
                        f"{MAX_GENERATION_WAIT_SECONDS}-second time limit."
                    )
                interaction = client.interactions.create(
                    model=MODEL,
                    input=(
                        f"Create one 15-second cinematic 3D Pixar Disney style animated video, portrait orientation. "
                        f"Visual brief: {prompt.strip()} "
                        "Features cute expressive cartoon characters, fluid animation, vibrant saturated colors, and comedic charm. "
                        "Generate silent video with no dialogue, narration, text, subtitles, logos, or watermark."
                    ),
                    response_format={
                        "type": "video",
                        "aspect_ratio": "9:16",
                        "resolution": RESOLUTION,
                    },
                    timeout=min(REQUEST_TIMEOUT_SECONDS, remaining),
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
                wait = min(wait, MAX_RATE_LIMIT_RETRY_DELAY_SECONDS)
                remaining = deadline - time.monotonic()
                if wait >= remaining:
                    raise TimeoutError(
                        f"Gemini video generation for scene {scene_number} ran out of "
                        "time while waiting to retry after HTTP 429."
                    ) from error
                log.warning(
                    "Scene %d rate-limited by Gemini (HTTP 429). Retry %d/%d in %.1fs",
                    scene_number, attempt + 1, MAX_RATE_LIMIT_RETRIES, wait,
                )
                time.sleep(wait)

        interaction = _wait_for_video(client, interaction, scene_number, deadline)
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


def _wait_for_video(client, interaction, scene_number: int, deadline: float):
    while True:
        video = getattr(interaction, "output_video", None)
        if getattr(video, "data", None):
            return interaction

        status = getattr(interaction, "status", None)
        status = str(getattr(status, "value", status) or "").lower().rsplit(".", 1)[-1]
        if status in {"failed", "cancelled", "canceled", "incomplete"}:
            detail = getattr(interaction, "error", None)
            raise RuntimeError(
                f"Gemini video generation failed for scene {scene_number} "
                f"(status={status}): {detail or 'provider returned no error details'}"
            )
        if status in {"completed", "succeeded"}:
            return interaction
        if status not in {"", "in_progress", "running", "queued", "processing"}:
            raise RuntimeError(
                f"Gemini returned unexpected status {status!r} for scene {scene_number}"
            )

        interaction_id = getattr(interaction, "id", None)
        if not interaction_id:
            raise RuntimeError(
                f"Gemini returned no video or interaction ID for scene {scene_number}"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Gemini video generation for scene {scene_number} did not finish within "
                f"{MAX_GENERATION_WAIT_SECONDS} seconds."
            )
        time.sleep(min(POLL_INTERVAL_SECONDS, remaining))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Gemini video generation for scene {scene_number} did not finish within "
                f"{MAX_GENERATION_WAIT_SECONDS} seconds."
            )
        interaction = client.interactions.get(
            interaction_id,
            timeout=min(REQUEST_TIMEOUT_SECONDS, remaining),
        )


def _generate_placeholders(prompts: list[str], work: Path) -> list[Path]:
    """Create local test-pattern clips without calling the paid video API."""
    paths = [work / f"scene_{index:02d}.mp4" for index in range(1, len(prompts) + 1)]
    for path in paths:
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=24:duration=15",
                    "-an", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-t", "15", str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as error:
            details = (error.stderr or "").strip()
            raise RuntimeError(
                f"Could not create dry-run placeholder clip {path.name}: "
                f"{details or 'FFmpeg returned a non-zero exit code'}"
            ) from error
    return paths


def generate_scenes(cfg: Config, prompts: list[str], work: Path) -> list[Path]:
    """Generate paid scenes after cost checks, or test-pattern clips in dry-run mode."""
    expected_count = math.ceil(cfg.target_seconds / MAX_CLIP_SECONDS)
    if not 30 <= cfg.target_seconds <= 60:
        raise ValueError("TARGET_SECONDS must be between 30 and 60")
    if len(prompts) != expected_count:
        raise ValueError(
            f"Expected {expected_count} AI scene prompts for a {cfg.target_seconds}-second video")
    if not cfg.dry_run and not cfg.ai_video_key:
        raise RuntimeError("OMNI_API_KEY (or GEMINI_API_KEY) is required for AI video generation")

    estimate = estimate_cost_usd(len(prompts))
    if not cfg.dry_run and (cfg.ai_video_max_usd <= 0 or estimate > cfg.ai_video_max_usd):
        raise RuntimeError(
            f"Refusing paid AI video generation: estimated video cost is about "
            f"${estimate:.2f} at 720p for {len(prompts)} clips, but "
            f"AI_VIDEO_MAX_USD is ${cfg.ai_video_max_usd:.2f}. "
            "This is a preflight estimate, not a provider-enforced billing cap. "
            "Increase the limit only after reviewing current Gemini pricing.")

    work.mkdir(parents=True, exist_ok=True)
    if cfg.dry_run:
        log.info("DRY_RUN=true; skipping paid Gemini video generation and creating placeholders")
        return _generate_placeholders(prompts, work)

    log.info("Generating %d AI scenes sequentially at 720p (estimated video cost: $%.2f)",
             len(prompts), estimate)
    paths = [work / f"scene_{index:02d}.mp4" for index in range(1, len(prompts) + 1)]
    deadline = time.monotonic() + MAX_GENERATION_WAIT_SECONDS
    return [
        _generate_one(cfg, prompt, path, index, deadline)
        for index, (prompt, path) in enumerate(zip(prompts, paths), start=1)
    ]
