"""Generate story-matched video scenes with Gemini Omni Flash."""
import base64
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from google import genai
from google.genai import types

from .config import Config
from .util import log

MODEL = "gemini-omni-1.2-flash"
MAX_CLIP_SECONDS = 15
ESTIMATED_USD_PER_SECOND_720P = 0.07
RESOLUTION = "720p"


def estimate_cost_usd(scene_count: int) -> float:
    return scene_count * MAX_CLIP_SECONDS * ESTIMATED_USD_PER_SECOND_720P


def _generate_one(cfg: Config, prompt: str, dest: Path, scene_number: int) -> Path:
    client = genai.Client(
        api_key=cfg.ai_video_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
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
    """Generate the complete scene set in parallel after a fail-closed cost check."""
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
    log.info("Generating %d AI scenes in parallel at 720p (estimated video cost: $%.2f)",
             len(prompts), estimate)
    paths = [work / f"scene_{index:02d}.mp4" for index in range(1, len(prompts) + 1)]
    with ThreadPoolExecutor(max_workers=len(prompts)) as executor:
        futures = [
            executor.submit(_generate_one, cfg, prompt, path, index)
            for index, (prompt, path) in enumerate(zip(prompts, paths), start=1)
        ]
        return [future.result() for future in futures]
