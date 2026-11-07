"""Step 3 - download openly licensed video clips from Wikimedia Commons."""
import html
import random
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import requests

from .config import Config
from .util import log, retry

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "DailyShorts/1.0 (https://github.com/k-nilesh04/daily-shorts)"
HEADERS = {"User-Agent": USER_AGENT}
FALLBACK_QUERIES = ["nature landscape", "city night", "clouds", "abstract light"]
MAX_CLIP_BYTES = 150 * 1024 * 1024
VIDEO_SUFFIXES = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".ogg", ".ogv", ".webm"}


@dataclass(frozen=True)
class Clip:
    path: Path
    title: str
    creator: str
    license: str
    license_url: str
    page_url: str

    def credit(self) -> dict[str, str]:
        return {
            "title": self.title,
            "creator": self.creator,
            "license": self.license,
            "license_url": self.license_url,
            "source_url": self.page_url,
        }


@retry(times=3, delay=3, exceptions=(requests.RequestException,))
def _search(query: str, per_page: int = 20) -> list[dict]:
    response = requests.get(
        API,
        headers=HEADERS,
        params={
            "action": "query",
            "generator": "search",
            "gsrsearch": f"filetype:video {query}",
            "gsrnamespace": 6,
            "gsrlimit": per_page,
            "prop": "imageinfo",
            "iiprop": "url|mime|size|extmetadata",
            "iiextmetadatafilter": "Artist|Credit|LicenseShortName|LicenseUrl",
            "format": "json",
            "formatversion": 2,
            "maxlag": 5,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise requests.HTTPError(f"Wikimedia Commons API error: {payload['error']}")
    pages = payload.get("query", {}).get("pages", [])
    return pages if isinstance(pages, list) else list(pages.values())


def _metadata_value(metadata: dict, key: str) -> str:
    item = metadata.get(key, {})
    value = item.get("value", "") if isinstance(item, dict) else ""
    return html.unescape(re.sub(r"<[^>]*>", "", str(value))).strip()


def _usable_license(metadata: dict) -> tuple[str, str] | None:
    label = _metadata_value(metadata, "LicenseShortName")
    license_url = _metadata_value(metadata, "LicenseUrl")
    normalized = re.sub(r"\s+", " ", label).strip().lower()

    if normalized == "cc0" or normalized.startswith("cc0 "):
        return label, license_url or "https://creativecommons.org/publicdomain/zero/1.0/"
    if normalized == "public domain" or normalized.startswith("public domain "):
        return label, license_url
    if re.fullmatch(r"cc by(?: \d+(?:\.\d+)?)?", normalized) and license_url:
        return label, license_url
    return None


def _candidate(page: dict) -> dict | None:
    images = page.get("imageinfo", [])
    if not images:
        return None
    info = images[0]
    if not str(info.get("mime", "")).startswith("video/") or not info.get("url"):
        return None

    metadata = info.get("extmetadata", {})
    license_info = _usable_license(metadata)
    if not license_info:
        return None
    label, license_url = license_info
    creator = _metadata_value(metadata, "Artist") or _metadata_value(metadata, "Credit")
    if label.lower().startswith("cc by") and not creator:
        return None

    title = str(page.get("title", "Wikimedia Commons video"))
    page_url = "https://commons.wikimedia.org/wiki/" + quote(title.replace(" ", "_"), safe=":_()")
    return {
        "pageid": page.get("pageid"),
        "title": title.removeprefix("File:"),
        "creator": creator,
        "license": label,
        "license_url": license_url,
        "page_url": page_url,
        "url": info["url"],
        "size": info.get("size"),
    }


@retry(times=3, delay=3, exceptions=(requests.RequestException,))
def _download(url: str, dest: Path) -> None:
    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as response:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_CLIP_BYTES:
            raise ValueError(f"Clip exceeds {MAX_CLIP_BYTES // (1024 * 1024)} MB download limit")
        total = 0
        try:
            with open(dest, "wb") as output:
                for chunk in response.iter_content(1 << 20):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_CLIP_BYTES:
                        raise ValueError(
                            f"Clip exceeds {MAX_CLIP_BYTES // (1024 * 1024)} MB download limit")
                    output.write(chunk)
        except (requests.RequestException, OSError, ValueError):
            dest.unlink(missing_ok=True)
            raise


def fetch(cfg: Config, keywords: list[str], needed: int, dest_dir: Path) -> list[Clip]:
    """Fetch reusable clips and their required source/license details."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    got: list[Clip] = []
    seen: set[int] = set()
    queries = list(keywords) + FALLBACK_QUERIES
    for query in queries:
        if len(got) >= needed:
            break
        try:
            pages = _search(query)
        except requests.RequestException as error:
            log.warning("Wikimedia Commons search '%s' failed: %s", query, error)
            continue

        candidates = [candidate for page in pages
                      if (candidate := _candidate(page))
                      and candidate["pageid"] not in seen]
        random.shuffle(candidates)
        for candidate in candidates:
            page_id = candidate["pageid"]
            if page_id is None:
                continue
            seen.add(page_id)
            suffix = Path(urlparse(candidate["url"]).path).suffix.lower()
            if suffix not in VIDEO_SUFFIXES:
                suffix = ".video"
            path = dest_dir / f"clip_{len(got):02d}_{page_id}{suffix}"
            if candidate["size"] and candidate["size"] > MAX_CLIP_BYTES:
                log.info("Skipping oversized Commons clip %s", candidate["title"])
                continue
            try:
                _download(candidate["url"], path)
            except (requests.RequestException, OSError, ValueError) as error:
                log.warning("Commons clip download failed for '%s': %s",
                            candidate["title"], error)
                continue
            clip = Clip(
                path=path,
                title=candidate["title"],
                creator=candidate["creator"],
                license=candidate["license"],
                license_url=candidate["license_url"],
                page_url=candidate["page_url"],
            )
            got.append(clip)
            log.info("Clip %d/%d: '%s' (Wikimedia Commons, %s)",
                     len(got), needed, candidate["title"], candidate["license"])
            break

    if not got:
        raise RuntimeError(
            "Could not download reusable video clips from Wikimedia Commons. "
            "Try different keywords; Commons may have no clips available under supported licenses.")
    while len(got) < needed:
        got.append(got[len(got) % len(got)])
    return got
