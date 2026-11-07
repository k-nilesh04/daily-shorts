"""Tiny JSON history so the same topic is not posted twice."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class HistoryError(ValueError):
    """Raised when the history file exists but is corrupt or the wrong shape."""


def load(path: Path) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HistoryError(
            f"history file {path} is not valid JSON (line {error.lineno}, "
            f"column {error.colno}: {error.msg}); fix or remove it") from error
    if not isinstance(items, list):
        raise HistoryError(
            f"history file {path} must contain a JSON list, got {type(items).__name__}")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise HistoryError(
                f"history file {path} entry {index} must be an object, "
                f"got {type(item).__name__}")
    return items


def recent_topics(path: Path, n: int = 80) -> list[str]:
    return [h.get("topic", "") for h in load(path)[-n:] if h.get("topic")]


def append(path: Path, topic: str, title: str, video_id: str | None) -> None:
    items = load(path)
    items.append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "topic": topic,
        "title": title,
        "video_id": video_id,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically so a crash cannot leave a truncated history file.
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(items[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    