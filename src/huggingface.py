"""Generate video clips via Hugging Face free Inference API.

Strategy: Scene chaining — generate one clip per scene prompt (5-10s each),
then stitch with FFmpeg. Falls back to image generation + FFmpeg motion
if text-to-video is unavailable on the free tier.
"""

import json
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config
from .util import log

HF_INFERENCE_API = "https://api-inference.huggingface.co/models"
HF_VIDEO_MODELS = [
    "cerspense/zeroscope_v2_576w",
    "damo-vilab/text-to-video-ms-1.7b",
    "ali-vilab/text-to-video-ms-1.7b",
]
HF_IMAGE_MODELS = [
    "black-forest-labs/FLUX.1-schnell",
    "stabilityai/stable-diffusion-xl-base-1.0",
    "runwayml/stable-diffusion-v1-5",
]
HF_WAIT_SECONDS = 30
HF_MAX_RETRIES = 3


def _hf_headers(cfg: Config) -> dict:
    headers = {"Content-Type": "application/json"}
    if getattr(cfg, "huggingface_api_key", ""):
        headers["Authorization"] = f"Bearer {cfg.huggingface_api_key}"
    return headers


def _hf_post(url: str, payload: dict, headers: dict, timeout: int = 120) -> bytes:
    """POST to HF Inference API and return raw bytes."""
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers)
    for attempt in range(HF_MAX_RETRIES):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except HTTPError as error:
            if error.code == 503:
                # Model is loading — wait and retry
                wait = HF_WAIT_SECONDS
                try:
                    body = error.read().decode("utf-8", "ignore")
                    import json as _json

                    info = _json.loads(body)
                    wait = info.get("estimated_time", wait)
                except Exception:  # noqa: BLE001
                    pass
                wait = min(wait, 120)
                if attempt < HF_MAX_RETRIES - 1:
                    log.warning(
                        "HF model loading (503). Waiting %.0fs before retry %d/%d",
                        wait,
                        attempt + 1,
                        HF_MAX_RETRIES,
                    )
                    time.sleep(wait)
                    continue
            raise
        except (URLError, TimeoutError, OSError) as error:
            if attempt < HF_MAX_RETRIES - 1:
                log.warning(
                    "HF request failed (%s). Retry %d/%d in 10s", error, attempt + 1, HF_MAX_RETRIES
                )
                time.sleep(10)
                continue
            raise
    raise RuntimeError("HF Inference API request failed after retries")


def _generate_video_clip(cfg: Config, prompt: str, dest: Path) -> bool:
    """Try to generate a video clip via HF text-to-video. Returns True on success."""
    headers = _hf_headers(cfg)
    for model in HF_VIDEO_MODELS:
        url = f"{HF_INFERENCE_API}/{model}"
        try:
            log.info("Trying HF video model: %s", model)
            raw = _hf_post(url, {"inputs": prompt}, headers, timeout=300)
            if raw and len(raw) > 1000:
                dest.write_bytes(raw)
                log.info(
                    "Generated HF video clip: %s (%d bytes) via %s", dest.name, len(raw), model
                )
                return True
        except Exception as error:  # noqa: BLE001
            log.warning("HF video model %s failed: %s", model, error)
    return False


def _generate_image(cfg: Config, prompt: str) -> bytes | None:
    """Generate an image via HF Inference API (free tier)."""
    headers = _hf_headers(cfg)
    for model in HF_IMAGE_MODELS:
        url = f"{HF_INFERENCE_API}/{model}"
        try:
            log.info("Trying HF image model: %s", model)
            raw = _hf_post(url, {"inputs": prompt}, headers, timeout=120)
            if raw and len(raw) > 1000:
                log.info("Generated HF image via %s (%d bytes)", model, len(raw))
                return raw
        except Exception as error:  # noqa: BLE001
            log.warning("HF image model %s failed: %s", model, error)
    return None


def _image_to_video(image_path: Path, dest: Path, duration: float, cfg: Config) -> bool:
    """Create a video from a static image using FFmpeg zoompan (Ken Burns effect)."""
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-loop",
                "1",
                "-i",
                str(image_path),
                "-vf",
                (
                    f"zoompan=z='min(zoom+0.0005,1.3)':"
                    f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    f"d={int(duration * 25)}:s=512x512:fps=25,"
                    f"scale=512:512,format=yuv420p"
                ),
                "-t",
                f"{duration:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "28",
                str(dest),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        if dest.is_file() and dest.stat().st_size > 0:
            log.info("Created motion video from image: %s", dest.name)
            return True
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        log.warning("FFmpeg image-to-video failed: %s", error)
    return False


def generate_scenes(cfg: Config, prompts: list[str], work: Path) -> list[Path]:
    """Generate one clip per scene prompt using HF free models.

    Tries text-to-video first, falls back to image + FFmpeg motion.
    """
    work.mkdir(parents=True, exist_ok=True)
    paths = []
    scene_duration = max(3.0, 45.0 / len(prompts)) if prompts else 9.0

    for i, prompt in enumerate(prompts, start=1):
        dest = work / f"scene_{i:02d}.mp4"
        if dest.is_file() and dest.stat().st_size > 1000:
            log.info("Reusing cached HF clip: %s", dest.name)
            paths.append(dest)
            continue

        log.info("Generating HF scene %d/%d", i, len(prompts))
        success = _generate_video_clip(cfg, prompt, dest)
        if not success:
            # Fallback: generate image + motion
            log.info("Video generation failed, falling back to image + motion for scene %d", i)
            img_path = work / f"scene_{i:02d}.png"
            img_bytes = _generate_image(cfg, prompt)
            if img_bytes:
                img_path.write_bytes(img_bytes)
                success = _image_to_video(img_path, dest, scene_duration, cfg)
            if not success:
                log.warning(
                    "Both video and image generation failed for scene %d. Creating placeholder.", i
                )
                # Last resort: solid color clip
                import subprocess

                try:
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-loglevel",
                            "error",
                            "-f",
                            "lavfi",
                            "-i",
                            f"color=c=0x1a1a2e:s=512x512:r=24:d={scene_duration}",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "ultrafast",
                            "-crf",
                            "28",
                            str(dest),
                        ],
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                except Exception as error:  # noqa: BLE001
                    log.error("Could not create placeholder clip: %s", error)

        if dest.is_file() and dest.stat().st_size > 0:
            paths.append(dest)
        else:
            log.error("Failed to generate scene %d", i)

    return paths
