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


def _prompt(cfg: Config, avoid: list[str], correction: str = "") -> str:
    target_words = int(cfg.target_seconds * 1.3)
    min_words = int(cfg.target_seconds * 1.0)
    max_words = int(cfg.target_seconds * 2)
    avoid_txt = "\n".join(f"- {t}" for t in avoid[-60:]) or "- (none yet)"
    scene_count = math.ceil(cfg.target_seconds / 15)
    language_rule = (
        "Use natural, witty, funny spoken Hinglish in Latin letters; do not use Devanagari. Use energetic comedic expressions and playful delivery."
        if cfg.language.lower() == "hinglish"
        else f"Write naturally and humorously in {cfg.language}."
    )
    return f"""You are a master comedy and storytelling creator for viral YouTube Shorts (style: cute 3D Pixar/Disney animated character comedy like talking cute babies, clumsy mischievous cats, and funny pet adventures).
Niche: {cfg.niche}
Language of narration/title/description: {cfg.language}

Write ONE hilarious, heartwarming, entertaining short story video.

CRITICAL LENGTH CONSTRAINTS (STRICT):
- Narration script length: MUST be concise, strictly between {min_words} and {target_words} words total.
- ABSOLUTE HARD CEILING: NEVER exceed {max_words} whitespace-separated words. Scripts over {max_words} words will be REJECTED.
- Keep sentences short, punchy, and comedic so it speaks comfortably within {cfg.target_seconds} seconds.
- Count every word in "script" before returning and verify len(script.split()) <= {max_words}.

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
- Each scene prompt must describe one 15-second, vertical 9:16 high-end 3D Pixar/Disney style animated CGI cartoon shot that directly illustrates this moment in the story.
- In each scene prompt, describe the character with cute expressive features (e.g. big glossy cartoon eyes, chubby cheeks, funny exaggerated facial expressions, playful slapstick body language), vibrant saturated colors, Pixar-level soft lighting, and a detailed animated environment.
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


def _parse(text: str, scene_count: int, max_words: int) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    data = json.loads(text)
    missing = REQUIRED - set(data)
    if missing:
        raise ValueError(f"Gemini JSON missing keys: {sorted(missing)}")
    if not isinstance(data["keywords"], list) or not data["keywords"]:
        raise ValueError("keywords must be a non-empty list")
    if (not isinstance(data["scene_prompts"], list)
            or len(data["scene_prompts"]) != scene_count
            or not all(isinstance(prompt, str) and prompt.strip()
                       for prompt in data["scene_prompts"])):
        raise ValueError(f"scene_prompts must contain exactly {scene_count} non-empty prompts")
    data["title"] = str(data["title"]).strip()[:95]
    data["script"] = " ".join(str(data["script"]).split())
    actual_words = len(data["script"].split())
    if actual_words > max_words:
        raise ScriptLengthError(actual_words, max_words)
    data["tags"] = [str(t).strip().lstrip("#") for t in data["tags"]][:12]
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


def generate(cfg: Config, avoid: list[str]) -> dict:
    if not cfg.gemini_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    scene_count = math.ceil(cfg.target_seconds / 15)
    max_words = int(cfg.target_seconds * 2)
    prompt = _prompt(cfg, avoid)
    for attempt in range(3):
        resp = _request(cfg, prompt)
        try:
            data = _parse(resp.text, scene_count, max_words)
        except ScriptLengthError as error:
            if attempt == 2:
                # Fallback: Auto-trim script to max_words to ensure the pipeline succeeds without error
                log.warning(
                    "Gemini script has %d words (limit %d) after 3 attempts. Auto-trimming to %d words.",
                    error.actual_words, max_words, max_words,
                )
                try:
                    raw_text = re.sub(r"^```(?:json)?|```$", "", resp.text, flags=re.MULTILINE).strip()
                    parsed = json.loads(raw_text)
                    parsed["script"] = _trim_to_word_limit(parsed["script"], max_words)
                    data = _parse(json.dumps(parsed), scene_count, max_words)
                    log.info("Script auto-trimmed to %d words: %s", len(data["script"].split()), data["title"])
                    return data
                except Exception:
                    raise error
            log.warning(
                "Gemini script has %d words (limit %d). Requesting a shorter rewrite (%d/2)",
                error.actual_words, max_words, attempt + 1,
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
            )
            continue

        log.info("Script ready: %s (%d words)", data["title"], len(data["script"].split()))
        return data
