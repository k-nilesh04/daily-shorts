"""Generate video assets with Gemini Omni or render an image/title via JSON2Video."""
import base64
import json
import math
import re
import subprocess
import time
from pathlib import Path

import httpx
import requests
from google import genai
from google.genai import errors, types

from .config import Config
from .util import log

# Kept as the documented default; Config.omni_model (OMNI_MODEL) overrides it.
MODEL = "gemini-omni-1.2-flash"
JSON2VIDEO_MODEL = "JSON2Video image-and-text render"
MAX_CLIP_SECONDS = 15
ESTIMATED_USD_PER_SECOND_720P = 0.07
RESOLUTION = "720p"
JSON2VIDEO_RESOLUTION = "instagram-story"
JSON2VIDEO_API_URL = "https://api.json2video.com/v2/movies"
JSON2VIDEO_MAX_WAIT_SECONDS = 15 * 60
JSON2VIDEO_POLL_INTERVAL_SECONDS = 3
JSON2VIDEO_REQUEST_TIMEOUT_SECONDS = 60
MAX_RATE_LIMIT_RETRIES = 3
RATE_LIMIT_RETRY_DELAY_SECONDS = 30
MAX_RATE_LIMIT_RETRY_DELAY_SECONDS = 120
REQUEST_TIMEOUT_SECONDS = 60
MAX_GENERATION_WAIT_SECONDS = 25 * 60
POLL_INTERVAL_SECONDS = 5
SCENE_MANIFEST_NAME = "manifest.json"
SCENE_FILE_PATTERN = re.compile(r"scene_\d{2}\.mp4")


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


def _backoff_seconds(attempt: int) -> float:
    return min(
        RATE_LIMIT_RETRY_DELAY_SECONDS * (2 ** attempt),
        MAX_RATE_LIMIT_RETRY_DELAY_SECONDS,
    )


def _retry_wait(error: errors.APIError | None, attempt: int) -> float:
    wait = _backoff_seconds(attempt)
    if error is not None:
        retry_after = _retry_after_seconds(error)
        if retry_after is not None:
            wait = max(wait, retry_after)
    return min(wait, MAX_RATE_LIMIT_RETRY_DELAY_SECONDS)


def _auth_error(error: errors.APIError) -> RuntimeError:
    return RuntimeError(
        f"Gemini rejected the video API request (HTTP {error.code}: {error.message}). "
        "Check that OMNI_API_KEY/GEMINI_API_KEY is valid, that the Generative Language "
        "API is enabled in the key's Google Cloud project, and that the project has "
        "paid-tier billing enabled for video generation."
    )


def _model_error(cfg: Config, error: errors.APIError) -> RuntimeError:
    model = getattr(cfg, "omni_model", MODEL) or MODEL
    return RuntimeError(
        f"Gemini video model {model!r} is unavailable (HTTP {error.code}: "
        f"{error.message}). Set OMNI_MODEL to a supported video model "
        "(see https://ai.google.dev/gemini-api/docs/video)."
    )


def _generate_one(
    cfg: Config, prompt: str, dest: Path, scene_number: int, deadline: float,
) -> Path:
    client = genai.Client(
        api_key=cfg.ai_video_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    model = getattr(cfg, "omni_model", MODEL) or MODEL
    try:
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"Gemini video generation exceeded its "
                    f"{MAX_GENERATION_WAIT_SECONDS}-second time limit."
                )
            try:
                interaction = client.interactions.create(
                    model=model,
                    input=(
                        "Create one 15-second cinematic 3D cartoon animated video, portrait orientation. "
                        f"Visual brief: {prompt.strip()} "
                        "Features expressive cartoon characters, fluid animation, vibrant saturated colors, "
                        "soft cinematic lighting, and comedic charm. "
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
                if error.code in (401, 403):
                    raise _auth_error(error) from error
                if error.code == 404:
                    raise _model_error(cfg, error) from error
                retryable = error.code == 429 or (
                    isinstance(error.code, int) and 500 <= error.code < 600)
                if not retryable:
                    raise RuntimeError(
                        f"Gemini video generation failed for scene {scene_number} "
                        f"(HTTP {error.code}: {error.message})."
                    ) from error
                if attempt == MAX_RATE_LIMIT_RETRIES:
                    if error.code == 429:
                        raise RuntimeError(
                            f"Gemini video generation for scene {scene_number} was rate-limited "
                            f"after {attempt + 1} attempts (HTTP 429: {error.message}). "
                            "Check the project's Gemini Omni rate limits, usage tier, and billing "
                            "at https://aistudio.google.com/rate-limit. Consider switching to "
                            "VIDEO_PROVIDER=json2video to avoid Gemini video rate limits."
                        ) from error
                    raise RuntimeError(
                        f"Gemini video generation for scene {scene_number} failed after "
                        f"{attempt + 1} attempts (HTTP {error.code}: {error.message}). "
                        "The provider may be temporarily unavailable; retry later."
                    ) from error
                wait = _retry_wait(error, attempt)
                remaining = deadline - time.monotonic()
                if wait >= remaining:
                    raise TimeoutError(
                        f"Gemini video generation for scene {scene_number} ran out of "
                        f"time while waiting to retry after HTTP {error.code}."
                    ) from error
                log.warning(
                    "Scene %d failed with HTTP %d from Gemini. Retry %d/%d in %.1fs",
                    scene_number, error.code, attempt + 1,
                    MAX_RATE_LIMIT_RETRIES, wait,
                )
                time.sleep(wait)
            except (httpx.TransportError, ConnectionError, TimeoutError) as error:
                # Connection resets, DNS failures, and provider timeouts are
                # transient. Retry with the same bounded backoff instead of
                # failing the whole (already paid) run.
                if attempt == MAX_RATE_LIMIT_RETRIES:
                    raise RuntimeError(
                        f"Could not reach the Gemini video API for scene {scene_number} "
                        f"after {attempt + 1} attempts: {error}. Check the runner's "
                        "network/egress and retry later."
                    ) from error
                wait = _backoff_seconds(attempt)
                remaining = deadline - time.monotonic()
                if wait >= remaining:
                    raise TimeoutError(
                        f"Gemini video generation for scene {scene_number} ran out of "
                        "time while retrying a network error."
                    ) from error
                log.warning(
                    "Scene %d connection error from Gemini (%s). Retry %d/%d in %.1fs",
                    scene_number, error, attempt + 1, MAX_RATE_LIMIT_RETRIES, wait,
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
        # Providers sometimes wrap base64 with newlines; decode a compact copy.
        video_bytes = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
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
        except FileNotFoundError as error:
            raise RuntimeError(
                "ffmpeg was not found; install FFmpeg and add it to PATH "
                "(https://ffmpeg.org/download.html)") from error
        except subprocess.CalledProcessError as error:
            details = (error.stderr or "").strip()
            raise RuntimeError(
                f"Could not create dry-run placeholder clip {path.name}: "
                f"{details or 'FFmpeg returned a non-zero exit code'}"
            ) from error
    return paths


def _json2video_http_error(
    error: requests.exceptions.HTTPError,
) -> RuntimeError:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    detail = ""
    if response is not None:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = str(payload.get("message") or payload.get("error") or "")
        if not detail:
            detail = (getattr(response, "text", "") or "").strip()[:300]
    if status in (401, 403):
        return RuntimeError(
            f"JSON2Video rejected the API key (HTTP {status}). Check JSON2VIDEO_API_KEY."
        )
    if status == 429:
        return RuntimeError(
            "JSON2Video rate limit or render credits exhausted (HTTP 429). "
            "Check the plan quota at https://json2video.com/."
        )
    suffix = f": {detail}" if detail else ""
    return RuntimeError(f"JSON2Video API error (HTTP {status}){suffix}")


def _generate_json2video(cfg: Config, work: Path) -> list[Path]:
    if not cfg.json2video_key:
        raise RuntimeError("JSON2VIDEO_API_KEY is required when VIDEO_PROVIDER=json2video")
    if not cfg.json2video_image_url:
        raise RuntimeError("JSON2VIDEO_IMAGE_URL must be a publicly accessible image URL")

    # Only the background image is rendered here. All on-screen text comes from
    # the caption track added by FFmpeg, so no fixed title/overlay is burned in.
    movie = {
        "resolution": JSON2VIDEO_RESOLUTION,
        "scenes": [{
            "duration": cfg.target_seconds,
            "elements": [
                {"type": "image", "src": cfg.json2video_image_url},
            ],
        }],
    }
    headers = {"x-api-key": cfg.json2video_key}
    for attempt in range(3):
        try:
            response = requests.post(
                JSON2VIDEO_API_URL,
                headers=headers,
                json=movie,
                timeout=JSON2VIDEO_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            break
        except requests.exceptions.ConnectionError as error:
            if attempt == 2:
                raise RuntimeError(
                    "Could not connect to JSON2Video API. Check your network "
                    "connection and JSON2VIDEO_API_KEY.") from error
            log.warning("JSON2Video connection failed (%s). Retry %d/3 in 5s",
                        error, attempt + 1)
            time.sleep(5)
        except requests.exceptions.Timeout as error:
            if attempt == 2:
                raise RuntimeError(
                    "JSON2Video API timed out. Try again later.") from error
            log.warning("JSON2Video request timed out. Retry %d/3 in 5s",
                        attempt + 1)
            time.sleep(5)
        except requests.exceptions.HTTPError as error:
            raise _json2video_http_error(error) from error
    else:
        raise RuntimeError("JSON2Video request failed after 3 attempts")
    project = response.json().get("project")
    if not isinstance(project, str) or not project:
        raise RuntimeError("JSON2Video response did not contain a project ID")

    deadline = time.monotonic() + JSON2VIDEO_MAX_WAIT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"JSON2Video project {project} did not finish within "
                f"{JSON2VIDEO_MAX_WAIT_SECONDS} seconds"
            )
        try:
            status_response = requests.get(
                JSON2VIDEO_API_URL,
                headers=headers,
                params={"project": project},
                timeout=min(JSON2VIDEO_REQUEST_TIMEOUT_SECONDS, remaining),
            )
            status_response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            raise _json2video_http_error(error) from error
        except requests.exceptions.RequestException as error:
            raise RuntimeError(
                f"Lost connection to JSON2Video while checking project {project}: "
                f"{error}. Retry later.") from error
        movie_status = status_response.json().get("movie")
        if not isinstance(movie_status, dict):
            raise RuntimeError("JSON2Video status response did not contain a movie")

        status = movie_status.get("status")
        if status == "done":
            video_url = movie_status.get("url")
            if not isinstance(video_url, str) or not video_url:
                raise RuntimeError("JSON2Video completed without returning a video URL")
            try:
                video_response = requests.get(
                    video_url, timeout=JSON2VIDEO_REQUEST_TIMEOUT_SECONDS)
                video_response.raise_for_status()
            except requests.exceptions.HTTPError as error:
                raise _json2video_http_error(error) from error
            except requests.exceptions.RequestException as error:
                raise RuntimeError(
                    f"Could not download the rendered JSON2Video file: {error}. "
                    "Retry later.") from error
            if not video_response.content:
                raise RuntimeError("JSON2Video returned an empty video")
            dest = work / "scene_01.mp4"
            dest.write_bytes(video_response.content)
            log.info("Generated JSON2Video clip: %s", dest.name)
            return [dest]
        if status in {"error", "timeout"}:
            raise RuntimeError(
                f"JSON2Video render failed (status={status}): "
                f"{movie_status.get('message') or 'provider returned no error details'}"
            )
        if status not in {"queued", "pending", "running"}:
            raise RuntimeError(f"JSON2Video returned unexpected status {status!r}")

        time.sleep(min(JSON2VIDEO_POLL_INTERVAL_SECONDS, remaining))


def _is_valid_clip(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _manifest_matches(work: Path, cfg: Config, prompts: list[str]) -> bool:
    """True when the cached scene directory belongs to this exact request."""
    try:
        manifest = json.loads((work / SCENE_MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, dict):
        return False
    return (
        manifest.get("prompts") == prompts
        and manifest.get("provider") == cfg.video_provider
        and bool(manifest.get("dry_run")) == cfg.dry_run
    )


def _write_manifest(work: Path, cfg: Config, prompts: list[str]) -> None:
    manifest = {
        "provider": cfg.video_provider,
        "dry_run": cfg.dry_run,
        "prompts": prompts,
    }
    (work / SCENE_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_scene_files(work: Path) -> None:
    for child in work.iterdir():
        if not child.is_file():
            continue
        if child.name == SCENE_MANIFEST_NAME or SCENE_FILE_PATTERN.fullmatch(child.name):
            child.unlink()


def generate_scenes(
    cfg: Config, prompts: list[str], work: Path, text: str = "Hello from Python",
) -> list[Path]:
    """Generate provider clips, or test-pattern clips in dry-run mode.

    Completed clips are cached alongside a manifest of the exact request so a
    retry after a late failure does not pay to regenerate finished scenes.
    """
    expected_count = math.ceil(cfg.target_seconds / MAX_CLIP_SECONDS)
    if not 30 <= cfg.target_seconds <= 60:
        raise ValueError("TARGET_SECONDS must be between 30 and 60")
    if len(prompts) != expected_count:
        raise ValueError(
            f"Expected {expected_count} AI scene prompts for a {cfg.target_seconds}-second video")
    if not cfg.dry_run and cfg.video_provider == "gemini" and not cfg.ai_video_key:
        raise RuntimeError("OMNI_API_KEY (or GEMINI_API_KEY) is required for AI video generation")

    work.mkdir(parents=True, exist_ok=True)
    if not _manifest_matches(work, cfg, prompts):
        _clear_scene_files(work)

    if cfg.video_provider == "json2video" and not cfg.dry_run:
        dest = work / "scene_01.mp4"
        if _is_valid_clip(dest):
            log.info("Reusing existing JSON2Video render: %s", dest.name)
            _write_manifest(work, cfg, prompts)
            return [dest]
        log.info("Rendering JSON2Video still-image template at %s", JSON2VIDEO_RESOLUTION)
        result = _generate_json2video(cfg, work)
        _write_manifest(work, cfg, prompts)
        return result

    paths = [work / f"scene_{index:02d}.mp4" for index in range(1, len(prompts) + 1)]
    pending = [
        (index, prompt, path)
        for index, (prompt, path) in enumerate(zip(prompts, paths), start=1)
        if not _is_valid_clip(path)
    ]
    if not pending:
        log.info("Reusing %d cached scene clip(s) from %s", len(paths), work)
        _write_manifest(work, cfg, prompts)
        return paths
    if len(pending) < len(paths):
        log.info("Reusing %d cached scene clip(s); generating %d",
                 len(paths) - len(pending), len(pending))

    if cfg.dry_run:
        log.info("DRY_RUN=true; skipping paid video generation and creating placeholders")
        result = _generate_placeholders(prompts, work)
        _write_manifest(work, cfg, prompts)
        return result

    estimate = estimate_cost_usd(len(pending))
    if cfg.ai_video_max_usd <= 0 or estimate > cfg.ai_video_max_usd:
        raise RuntimeError(
            f"Refusing paid AI video generation: estimated video cost is about "
            f"${estimate:.2f} at 720p for {len(pending)} clip(s), but "
            f"AI_VIDEO_MAX_USD is ${cfg.ai_video_max_usd:.2f}. "
            "This is a preflight estimate, not a provider-enforced billing cap. "
            "Increase the limit only after reviewing current Gemini pricing.")

    log.info("Generating %d AI scene(s) sequentially at 720p (estimated video cost: $%.2f)",
             len(pending), estimate)
    deadline = time.monotonic() + MAX_GENERATION_WAIT_SECONDS
    for index, prompt, path in pending:
        _generate_one(cfg, prompt, path, index, deadline)
    _write_manifest(work, cfg, prompts)
    return paths
