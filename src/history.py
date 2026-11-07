"""Tiny JSON history so the same topic is not posted twice."""
import json
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


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
    path.write_text(json.dumps(items[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
