"""Step 1 - ask Gemini for the video script + YouTube metadata as strict JSON."""
import json
import math
import re

from google import genai
from google.genai import types

from .config import Config
from .util import log, retry

REQUIRED = {
    "topic", "title", "script", "description", "tags", "keywords", "scene_prompts",
}

# Measured with edge-tts 7.3.1, voice hi-IN-MadhurNeural, rate +0%:
# ~2.5 spoken words per second. The old budget (target * 1.3 words) produced
# roughly half the requested duration, so scripts now aim at the real rate.
WORDS_PER_SECOND = 2.0
MIN_WORDS_RATIO = 0.93
SECONDS_PER_SCENE = 15
MAX_SHORT_SECONDS = 60
OVERRUN_ALLOWANCE_SECONDS = 2
MAX_GENERATE_ATTEMPTS = 3


def word_budget(target_seconds: int, words_per_second: float = WORDS_PER_SECOND) -> tuple[int, int, int]:
    """Return (min_words, target_words, max_words) for the requested duration.

    The maximum is derived from the largest narration the renderer accepts, so a
    script can never be longer than the pipeline is willing to publish.
    """
    words_per_second = max(1.0, float(words_per_second))
    target_words = round(target_seconds * words_per_second)
    min_words = round(target_seconds * words_per_second * MIN_WORDS_RATIO)
    max_seconds = min(target_seconds + OVERRUN_ALLOWANCE_SECONDS, MAX_SHORT_SECONDS)
    max_words = round(max_seconds * words_per_second)
    return min_words, target_words, max_words


class ScriptLengthError(ValueError):
    def __init__(self, actual_words: int, max_words: int) -> None:
        self.actual_words = actual_words
        super().__init__(f"script has {actual_words} words; maximum is {max_words}")


def _trim_to_word_limit(script: str, max_words: int) -> str:
    """Trim a script to fit within max_words, preserving complete sentences if possible."""
    words = script.split()
    if len(words) <= max_words:
        return script
    truncated = " ".join(words[:max_words])
    match = re.search(r"^(.*[.!?])\s+[^.!?]*$", truncated)
    if match and len(match.group(1).split()) >= int(max_words * 0.7):
        return match.group(1)
    return truncated.rstrip(",;:- ") + "."


def _prompt(cfg: Config, avoid: list[str], correction: str = "", words_per_second: float = WORDS_PER_SECOND) -> str:
    min_words, target_words, max_words = word_budget(cfg.target_seconds, words_per_second)
    avoid_txt = "\n".join(f"- {t}" for t in avoid[-60:]) or "- (none yet)"
    scene_count = math.ceil(cfg.target_seconds / SECONDS_PER_SCENE)
    language_rule = (
        "Use natural, witty, funny spoken Hinglish in Latin letters; do not use Devanagari. Use energetic comedic expressions and playful delivery."
        if cfg.language.lower() == "hinglish"
        else f"Write naturally and humorously in {cfg.language}."
    )
    return f"""You are a master comedy and storytelling creator for viral YouTube Shorts. The style is polished 3D cartoon animation with expressive characters, warm humor, and playful pet/baby adventures.
Niche: {cfg.niche}
Language of narration/title/description: {cfg.language}

Write ONE hilarious, heartwarming, entertaining short story video.

CRITICAL LENGTH CONSTRAINTS (STRICT):
- Narration script length: between {min_words} and {max_words} words total. Aim for about {target_words} words, which is roughly {cfg.target_seconds} seconds of speech at a normal pace.
- ABSOLUTE HARD CEILING: NEVER exceed {max_words} whitespace-separated words. Scripts over {max_words} words will be REJECTED.
- Keep sentences short, punchy, and comedic so it speaks comfortably within {cfg.target_seconds} seconds.
- Count every word in "script" before returning and verify {min_words} <= len(script.split()) <= {max_words}.

Story Rules:
- {language_rule}
- Concept: A funny character (e.g. a cute chubby baby with hilarious adult plans, a mischievous cat causing comedy chaos in a clinic or kitchen, or a dramatic playful pet).
- Hook: The very first sentence is an instant comedic hook (e.g. an unexpected funny situation or question). No boring greetings like 'hello' or 'welcome'.
- Escalation & Pacing: Keep the story super lively and fast-paced. Show the character trying something ambitious, failing in a funny cute way, and creating escalating comedic chaos.
- Punchline: Deliver a hilarious or cute twist ending that leaves viewers smiling.
- Call to action: End with a funny short closing line asking viewers to like, comment, and subscribe.
- Narration script format: Plain sentences only: no emojis, hashtags, stage directions or markdown in "script" (audio TTS reads plain text).
- Do NOT repeat any of these past topics:
{avoid_txt}
- Create exactly {scene_count} visually distinct, chronological scene prompts for AI video generation.
- Each scene prompt must describe one 15-second, vertical 9:16 polished 3D cartoon animation shot that directly illustrates this moment in the story.
- In each scene prompt, describe the character with cute expressive features (e.g. big glossy cartoon eyes, chubby cheeks, funny exaggerated facial expressions, playful slapstick body language), vibrant saturated colors, soft cinematic lighting, and a detailed animated environment.
- Scene prompts must be in English and must request no speech, no text, no subtitles, no logos, and no watermarks.
{correction}

Return ONLY a JSON object with exactly these keys:
{{
  "topic": "3-8 word topic label (in English)",
  "title": "catchy funny YouTube title with cute/funny vibes, max 80 chars, in {cfg.language}",
  "script": "the full narration text",
  "description": "2-3 sentence funny description with comedy hashtags in {cfg.language}",
  "tags": ["8-12 short tags including funny, animation, comedy, cute, shorts"],
  "keywords": ["6 ENGLISH visual concepts from the story, in story order"],
  "scene_prompts": ["English prompt for scene 1", "English prompt for scene 2"]
}}"""


def _strip_code_fences(text: str) -> str:
    return re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()


def _response_text(response) -> str:
    """Return the model text or fail with an actionable message."""
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise ValueError(
            "Gemini returned no text content; the response may have been blocked "
            "by safety filters or returned empty")
    return text


def _parse(text: str, scene_count: int, max_words: int) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Gemini returned an empty response body")
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Gemini returned invalid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}") from error
    if not isinstance(data, dict):
        raise ValueError(f"Gemini JSON must be an object, got {type(data).__name__}")
    missing = REQUIRED - set(data)
    if missing:
        raise ValueError(f"Gemini JSON missing keys: {sorted(missing)}")
    for key in ("topic", "title", "script", "description"):
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Gemini JSON '{key}' must be a non-empty string")
    if (not isinstance(data["tags"], list) or not data["tags"]
            or not all(isinstance(tag, str) and tag.strip() for tag in data["tags"])):
        raise ValueError("Gemini JSON 'tags' must be a non-empty list of strings")
    if (not isinstance(data["keywords"], list) or not data["keywords"]
            or not all(isinstance(word, str) and word.strip()
                       for word in data["keywords"])):
        raise ValueError("Gemini JSON 'keywords' must be a non-empty list of strings")
    if (not isinstance(data["scene_prompts"], list)
            or len(data["scene_prompts"]) != scene_count
            or not all(isinstance(prompt, str) and prompt.strip()
                       for prompt in data["scene_prompts"])):
        raise ValueError(f"scene_prompts must contain exactly {scene_count} non-empty prompts")

    data["topic"] = data["topic"].strip()[:120]
    data["title"] = data["title"].strip()[:95]
    data["script"] = " ".join(data["script"].split())
    data["description"] = data["description"].strip()
    actual_words = len(data["script"].split())
    if actual_words > max_words:
        raise ScriptLengthError(actual_words, max_words)
    data["tags"] = [tag.strip().lstrip("#") for tag in data["tags"]][:12]
    data["keywords"] = [word.strip() for word in data["keywords"]]
    return data


@retry(times=3, delay=6)
def _request(cfg: Config, prompt: str):
    if not cfg.gemini_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    client = genai.Client(
        api_key=cfg.gemini_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    try:
        return client.models.generate_content(
            model=cfg.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.9,
            ),
        )
    finally:
        client.close()


def _auto_trim(resp, scene_count: int, max_words: int) -> dict | None:
    """Last-resort trim of the final overlong response, or None if unusable."""
    try:
        parsed = json.loads(_strip_code_fences(_response_text(resp)))
        if not isinstance(parsed, dict) or "script" not in parsed:
            raise ValueError("previous response was not a JSON object with a script")
        parsed["script"] = _trim_to_word_limit(str(parsed["script"]), max_words)
        return _parse(json.dumps(parsed), scene_count, max_words)
    except (TypeError, ValueError) as error:
        log.error("Could not auto-trim the overlong script: %s", error)
        return None


def generate(cfg: Config, avoid: list[str], words_per_second: float = WORDS_PER_SECOND) -> dict:
    if not cfg.gemini_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    scene_count = math.ceil(cfg.target_seconds / SECONDS_PER_SCENE)
    min_words, _target_words, max_words = word_budget(cfg.target_seconds, words_per_second)
    prompt = _prompt(cfg, avoid, words_per_second=words_per_second)
    last_error: Exception | None = None

    for attempt in range(MAX_GENERATE_ATTEMPTS):
        resp = _request(cfg, prompt)
        try:
            data = _parse(_response_text(resp), scene_count, max_words)
        except ScriptLengthError as error:
            last_error = error
            if attempt == MAX_GENERATE_ATTEMPTS - 1:
                log.warning(
                    "Gemini script has %d words (limit %d) after %d attempts. "
                    "Auto-trimming to %d words.",
                    error.actual_words, max_words, MAX_GENERATE_ATTEMPTS, max_words,
                )
                trimmed = _auto_trim(resp, scene_count, max_words)
                if trimmed is None:
                    raise error
                log.info("Script auto-trimmed to %d words: %s",
                         len(trimmed["script"].split()), trimmed["title"])
                return trimmed
            log.warning(
                "Gemini script has %d words (limit %d). Requesting a shorter rewrite (%d/%d)",
                error.actual_words, max_words, attempt + 1, MAX_GENERATE_ATTEMPTS - 1,
            )
            prompt = _prompt(
                cfg,
                avoid,
                correction=(
                    f"IMPORTANT: Your previous narration was {error.actual_words} words, exceeding "
                    f"the hard limit of {max_words}. Rewrite the complete story much shorter. "
                    f"Keep the script at or below {max_words} whitespace-separated words; "
                    "count the words before returning the JSON."
                ),
                words_per_second=words_per_second,
            )
            continue
        except ValueError as error:
            last_error = error
            if attempt == MAX_GENERATE_ATTEMPTS - 1:
                raise RuntimeError(
                    f"Gemini did not return a valid script after "
                    f"{MAX_GENERATE_ATTEMPTS} attempts: {error}") from error
            log.warning(
                "Gemini response was invalid (%s). Requesting a corrected response (%d/%d)",
                error, attempt + 1, MAX_GENERATE_ATTEMPTS - 1,
            )
            prompt = _prompt(
                cfg,
                avoid,
                correction=(
                    f"IMPORTANT: your previous response was rejected: {error}. "
                    "Return ONLY one JSON object with exactly these keys: topic, title, "
                    "script, description, tags, keywords, scene_prompts. "
                    f"Use exactly {scene_count} scene prompts and keep the script between "
                    f"{min_words} and {max_words} words."
                ),
                words_per_second=words_per_second,
            )
            continue

        log.info("Script ready: %s (%d words)", data["title"], len(data["script"].split()))
        return data

    raise RuntimeError(f"Gemini script generation failed: {last_error}")
