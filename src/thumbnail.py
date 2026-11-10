"""Generate a YouTube thumbnail from the script using Gemini image generation (nano banana)."""
import base64
from pathlib import Path

from google import genai
from google.genai import errors, types

from .config import Config
from .util import log


THUMBNAIL_WIDTH = 1280
THUMBNAIL_HEIGHT = 720
# Models to try in order (nano banana / Gemini image generation)
THUMBNAIL_MODELS = [
    "gemini-2.0-flash-exp",
    "gemini-2.5-flash-preview-image-generation",
    "gemini-2.0-flash",
]


def _build_prompt(title: str, script: str) -> str:
    """Build an image-generation prompt from the script title and content."""
    synopsis = script.strip()[:300]
    return (
        f"Create a YouTube thumbnail image (1280x720, 16:9 landscape) for a funny "
        f"3D animated comedy short titled: '{title}'. "
        f"Story synopsis: {synopsis}. "
        "The thumbnail must be eye-catching and click-worthy: bold, expressive "
        "3D cartoon characters with exaggerated funny faces and comedic poses, "
        "vibrant saturated colors, dramatic cinematic lighting, and a sense of "
        "chaos or humor. Include the title text in large, bold, readable font "
        "with a thick outline and drop shadow. Style: Pixar/Disney-quality 3D "
        "cartoon render, high resolution, professional YouTube thumbnail. "
        "No watermarks, no logos, no extra text beyond the title."
    )


def generate(
    cfg: Config,
    title: str,
    script: str,
    out: Path,
) -> Path | None:
    """Generate a thumbnail image and save it to ``out``.

    Returns the output path on success, or ``None`` if generation failed
    (non-fatal -- the upload proceeds without a custom thumbnail).
    """
    configured = getattr(cfg, "thumbnail_model", "") or ""
    if configured:
        models_to_try = [configured] + [m for m in THUMBNAIL_MODELS if m != configured]
    else:
        models_to_try = list(THUMBNAIL_MODELS)

    # Also try the gemini image generation model name
    if "gemini-2.5-flash-image" not in models_to_try:
        models_to_try.append("gemini-2.5-flash-image")

    if not cfg.gemini_key:
        log.warning("No Gemini API key -- skipping thumbnail generation")
        return None

    prompt = _build_prompt(title, script)
    client = genai.Client(api_key=cfg.gemini_key)

    response = None
    last_error = None
    for model in models_to_try:
        try:
            log.info("Trying thumbnail model: %s", model)
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"],
                ),
            )
            # Check if response contains an image
            has_image = False
            for candidate in getattr(response, "candidates", []) or []:
                content = getattr(candidate, "content", None)
                for part in getattr(content, "parts", []) or []:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        has_image = True
                        break
                if has_image:
                    break
            if has_image:
                log.info("Thumbnail generated successfully with model: %s", model)
                break
            else:
                log.warning("Model %s returned no image, trying next...", model)
                response = None
        except errors.APIError as error:
            log.warning("Thumbnail model %s failed (HTTP %s: %s)", model, error.code, error.message)
            last_error = error
            response = None
        except Exception as error:  # noqa: BLE001
            log.warning("Thumbnail model %s failed: %s", model, error)
            last_error = error
            response = None

    client.close()

    if response is None:
        log.warning("All thumbnail models failed. Last error: %s. Skipping thumbnail.", last_error)
        return None

    # Extract image bytes from the response
    image_bytes = None
    mime_type = "image/png"
    try:
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    image_bytes = inline.data
                    mime_type = getattr(inline, "mime_type", mime_type) or mime_type
                    break
            if image_bytes:
                break
    except Exception as error:  # noqa: BLE001
        log.warning("Could not extract thumbnail image: %s", error)
        return None

    if not image_bytes:
        log.warning("Gemini returned no image for thumbnail. Skipping.")
        return None

    # Decode if base64-encoded string
    if isinstance(image_bytes, str):
        try:
            image_bytes = base64.b64decode(image_bytes)
        except Exception:  # noqa: BLE001
            log.warning("Could not decode thumbnail image data. Skipping.")
            return None

    # Resize to 1280x720 if Pillow is available
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(image_bytes))
        if img.size != (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT):
            img = img.resize(
                (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT),
                Image.LANCZOS,
            )
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "JPEG", quality=90)
        log.info("Generated thumbnail: %s (%dx%d)", out.name, THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
        return out
    except ImportError:
        # No Pillow - save raw bytes
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(image_bytes)
        log.info("Generated thumbnail: %s (raw, no resize)", out.name)
        return out
    except Exception as error:  # noqa: BLE001
        log.warning("Could not process thumbnail image: %s. Skipping.", error)
        return None