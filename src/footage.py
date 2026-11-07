"""Step 3 - download portrait stock clips from Pexels (free API)."""
import random
from pathlib import Path

import requests

from .config import Config
from .util import log, retry

API = "https://api.pexels.com/videos/search"
FALLBACK_QUERIES = ["abstract light", "city night", "nature landscape", "clouds timelapse"]


@retry(times=3, delay=3, exceptions=(requests.RequestException,))
def _search(cfg: Config, query: str, per_page: int = 8) -> list[dict]:
    r = requests.get(
        API,
        headers={"Authorization": cfg.pexels_key},
        params={"query": query, "orientation": "portrait", "size": "medium", "per_page": per_page},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("videos", [])


def _pick_file(video: dict) -> str | None:
    """Choose an mp4 close to 1080 wide, portrait if possible."""
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and f.get("link")]
    if not files:
        return None
    portrait = [f for f in files if (f.get("height") or 0) >= (f.get("width") or 0)] or files
    portrait.sort(key=lambda f: abs((f.get("width") or 0) - 1080))
    return portrait[0]["link"]


@retry(times=3, delay=3, exceptions=(requests.RequestException,))
def _download(url: str, dest: Path) -> None:
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def fetch(cfg: Config, keywords: list[str], needed: int, dest_dir: Path) -> list[Path]:
    """Return `needed` clip paths (re-using clips only if Pexels returns too few)."""
    if not cfg.pexels_key:
        raise RuntimeError("PEXELS_API_KEY is not set")
    dest_dir.mkdir(parents=True, exist_ok=True)
    got: list[Path] = []
    seen: set[int] = set()
    queries = list(keywords) + FALLBACK_QUERIES
    i = 0
    while len(got) < needed and i < len(queries) * 2:
        q = queries[i % len(queries)]
        i += 1
        try:
            videos = [v for v in _search(cfg, q) if v["id"] not in seen]
        except requests.RequestException as e:
            log.warning("Pexels search '%s' failed: %s", q, e)
            continue
        if not videos:
            continue
        v = random.choice(videos[:4])
        link = _pick_file(v)
        if not link:
            continue
        seen.add(v["id"])
        path = dest_dir / f"clip_{len(got):02d}_{v['id']}.mp4"
        try:
            _download(link, path)
        except requests.RequestException as e:
            log.warning("Download failed for %s: %s", q, e)
            continue
        got.append(path)
        log.info("Clip %d/%d: '%s' (pexels %s)", len(got), needed, q, v["id"])
    if not got:
        raise RuntimeError("Could not download any stock footage")
    while len(got) < needed:  # re-use if short
        got.append(got[len(got) % max(1, len(set(got)))])
    return got
