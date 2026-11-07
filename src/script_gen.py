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


def _prompt(cfg: Config, avoid: list[str], correction: str = "") -> str:
    words = int(cfg.target_seconds * 1.5)
    max_words = int(cfg.target_seconds * 2)
    avoid_txt = "\n".join(f"- {t}" for t in avoid[-60:]) or "- (none yet)"
    scene_count = math.ceil(cfg.target_seconds / 15)
    language_rule = (
        "Use natural spoken Hinglish in Latin letters; do not use Devanagari."
        if cfg.language.lower() == "hinglish"
        else f"Write naturally in {cfg.language}."
    )
    return f"""You write scripts for a faceless YouTube Shorts channel.
Niche: {cfg.niche}
Language of narration/title/description: {cfg.language}

Write ONE new short video. Rules:
- Narration: about {words} words, and never more than {max_words} whitespace-separated words.
  Keep the spoken story concise enough to fit within {cfg.target_seconds} seconds.
- {language_rule}
- First sentence is a strong hook (a surprising claim or question). No greetings, no "welcome".
- Keep the story vivid and fast, not like an encyclopedia entry: use conversational phrasing,
  concrete imagery, varied sentence lengths, and an escalating reveal.
- Give the viewer a reason to stay: open a curiosity gap, answer it with a clear explanation,
  and finish with one memorable takeaway.
- Only include facts you are confident are true. No invented statistics, quotes or names.
- End with a short closing line that makes people want to follow or comment.
- Plain sentences only: no emojis, hashtags, stage directions or markdown in "script".
- Do NOT repeat any of these past topics:
{avoid_txt}
- Create exactly {scene_count} visually distinct, chronological scene prompts for AI video generation.
- Each scene prompt must describe one 15-second, vertical 9:16 cinematic documentary shot that
  directly illustrates this story. Use specific era-appropriate objects, locations, and action.
- Scene prompts must be in English, must not add facts absent from the narration, and must request
  no speech, no captions, no writing, no logos, and no watermarks. The pipeline adds narration/captions.
{correction}

Return ONLY a JSON object with exactly these keys:
{{
  "topic": "3-8 word topic label (in English)",
  "title": "catchy YouTube title, max 80 chars, in {cfg.language}",
  "script": "the full narration text",
  "description": "2-3 sentence description in {cfg.language}",
  "tags": ["8-12 short tags"],
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
                raise
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
