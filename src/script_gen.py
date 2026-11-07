"""Step 1 - ask Gemini for the video script + YouTube metadata as strict JSON."""
import json
import re

from google import genai
from google.genai import types

from .config import Config
from .util import log, retry

REQUIRED = {"topic", "title", "script", "description", "tags", "keywords", "hook_prompt"}


def _prompt(cfg: Config, avoid: list[str]) -> str:
    words = int(cfg.target_seconds * 2.5)  # ~2.5 spoken words per second
    avoid_txt = "\n".join(f"- {t}" for t in avoid[-60:]) or "- (none yet)"
    return f"""You write scripts for a faceless YouTube Shorts channel.
Niche: {cfg.niche}
Language of narration/title/description: {cfg.language}

Write ONE new short video. Rules:
- Narration: about {words} words (a {cfg.target_seconds}-second read), spoken style.
- First sentence is a strong hook (a surprising claim or question). No greetings, no "welcome".
- Only include facts you are confident are true. No invented statistics, quotes or names.
- End with a short closing line that makes people want to follow or comment.
- Plain sentences only: no emojis, hashtags, stage directions or markdown in "script".
- Do NOT repeat any of these past topics:
{avoid_txt}

Return ONLY a JSON object with exactly these keys:
{{
  "topic": "3-8 word topic label (in English)",
  "title": "catchy YouTube title, max 80 chars, in {cfg.language}",
  "script": "the full narration text",
  "description": "2-3 sentence description in {cfg.language}",
  "tags": ["8-12 short tags"],
  "keywords": ["6 ENGLISH stock-footage search phrases, 1-3 words each, concrete visuals, in story order"],
  "hook_prompt": "one ENGLISH sentence describing a striking 6-second opening shot for this topic"
}}"""


def _parse(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    data = json.loads(text)
    missing = REQUIRED - set(data)
    if missing:
        raise ValueError(f"Gemini JSON missing keys: {sorted(missing)}")
    if not isinstance(data["keywords"], list) or not data["keywords"]:
        raise ValueError("keywords must be a non-empty list")
    data["title"] = str(data["title"]).strip()[:95]
    data["script"] = " ".join(str(data["script"]).split())
    data["tags"] = [str(t).strip().lstrip("#") for t in data["tags"]][:12]
    return data


@retry(times=3, delay=6)
def generate(cfg: Config, avoid: list[str]) -> dict:
    if not cfg.gemini_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    client = genai.Client(
        api_key=cfg.gemini_key,
        http_options=types.HttpOptions(api_version="v1beta"),
    )
    resp = client.models.generate_content(
        model=cfg.gemini_model,
        contents=_prompt(cfg, avoid),
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.9,
        ),
    )
    data = _parse(resp.text)
    log.info("Script ready: %s (%d words)", data["title"], len(data["script"].split()))
    return data
