"""Step 5 - upload to YouTube with the Data API v3 (OAuth refresh token)."""
import time
from pathlib import Path

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .config import Config
from .util import log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
CREDENTIAL_NAMES = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")


def missing_credentials(cfg: Config) -> list[str]:
    values = {
        "YT_CLIENT_ID": cfg.yt_client_id,
        "YT_CLIENT_SECRET": cfg.yt_client_secret,
        "YT_REFRESH_TOKEN": cfg.yt_refresh_token,
    }
    return [name for name in CREDENTIAL_NAMES if not values[name]]


def _credentials(cfg: Config) -> Credentials:
    return Credentials(
        token=None,
        refresh_token=cfg.yt_refresh_token,
        token_uri=TOKEN_URI,
        client_id=cfg.yt_client_id,
        client_secret=cfg.yt_client_secret,
        scopes=SCOPES,
    )


def _granted_scopes(creds: Credentials) -> list[str]:
    """Return the scopes Google actually granted for this access token."""
    try:
        response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"access_token": creds.token},
            timeout=10,
        )
        if response.status_code != 200:
            return []
        payload = response.json()
        scope = payload.get("scope", "")
        return [item for item in str(scope).split() if item]
    except (requests.RequestException, ValueError):
        return []


def _refresh_error_message(error: Exception) -> str:
    text = str(error)
    lowered = text.lower()
    if "invalid_grant" in lowered:
        return (
            "YouTube refresh token is expired or revoked (invalid_grant). Re-run "
            "`python scripts/get_youtube_token.py client_secret.json` and update the "
            "YT_REFRESH_TOKEN secret. While the OAuth consent screen is in 'Testing' "
            "mode, Google expires refresh tokens after 7 days."
        )
    if "invalid_client" in lowered or "unauthorized_client" in lowered:
        return (
            "YouTube OAuth client credentials are invalid (invalid_client). Check that "
            "YT_CLIENT_ID and YT_CLIENT_SECRET match the Desktop OAuth client used to "
            "create the refresh token."
        )
    return (
        "Could not refresh the YouTube OAuth token: "
        f"{text}. Re-run `python scripts/get_youtube_token.py client_secret.json` and "
        "update the YT_* repository secrets."
    )


def _http_error_message(error: HttpError) -> str:
    status = getattr(getattr(error, "resp", None), "status", None)
    if status == 403:
        content = getattr(error, "content", b"") or b""
        text = content.decode("utf-8", "ignore").lower()
        if "insufficient" in text or "insufficient" in str(error).lower():
            return (
                "YouTube rejected the token because it lacks the youtube.upload scope "
                "(insufficientPermissions). Re-run "
                "`python scripts/get_youtube_token.py client_secret.json` with the same "
                "Desktop OAuth client and replace YT_REFRESH_TOKEN. Make sure the OAuth "
                "consent screen lists the https://www.googleapis.com/auth/youtube.upload "
                "scope."
            )
        return (
            "YouTube upload permission denied (HTTP 403). Enable the YouTube Data API v3 "
            "in the Google Cloud project, add the channel account as an OAuth test user, "
            "and make sure the refresh token was created with the youtube.upload scope."
        )
    if status == 401:
        return (
            "YouTube rejected the OAuth token (HTTP 401). Re-run "
            "`python scripts/get_youtube_token.py client_secret.json` and update the "
            "YT_* repository secrets."
        )
    return f"YouTube API error (HTTP {status}): {error}"


def verify(cfg: Config) -> str:
    """Validate the credentials before paid work; returns the channel title."""
    missing = missing_credentials(cfg)
    if missing:
        raise RuntimeError(
            "Missing YouTube upload credentials: " + ", ".join(missing)
            + ". Add them as repository Actions secrets."
        )
    creds = _credentials(cfg)
    try:
        creds.refresh(Request())
    except RefreshError as error:
        raise RuntimeError(_refresh_error_message(error)) from error

    granted = _granted_scopes(creds)
    if granted and "https://www.googleapis.com/auth/youtube.upload" not in granted:
        raise RuntimeError(
            "The refresh token does not include the youtube.upload scope. "
            f"Granted scopes: {', '.join(granted) or '(none)'}. Re-run "
            "`python scripts/get_youtube_token.py client_secret.json` with the "
            "same Desktop OAuth client and replace YT_REFRESH_TOKEN. Also make "
            "sure the OAuth consent screen lists "
            "https://www.googleapis.com/auth/youtube.upload as a scope."
        )

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    try:
        response = yt.channels().list(part="snippet", mine=True).execute()
    except HttpError as error:
        raise RuntimeError(_http_error_message(error)) from error
    items = response.get("items") or []
    if not items:
        raise RuntimeError(
            "The YouTube credentials are valid but no channel is associated with that "
            "Google account. Sign in with the channel owner account when creating the "
            "refresh token."
        )
    title = items[0].get("snippet", {}).get("title") or "(unnamed channel)"
    log.info("YouTube credentials verified for channel: %s", title)
    return title


def upload(cfg: Config, video: Path, meta: dict) -> str:
    missing = missing_credentials(cfg)
    if missing:
        raise RuntimeError(
            "Missing YouTube upload credentials: " + ", ".join(missing)
            + ". Add them as repository Actions secrets."
        )
    creds = _credentials(cfg)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    description = meta["description"]
    description += "\n\n#Shorts #Funny #Animation #Comedy #Viral"
    tags = list(meta.get("tags", []))
    for t in ["Shorts", "funny", "comedy", "animation", "3danimation", "cartoon"]:
        if t not in tags:
            tags.append(t)

    category_id = getattr(cfg, "yt_category_id", "23")  # 23 = Comedy
    body = {
        "snippet": {
            "title": meta["title"][:100],
            "description": description,
            "tags": tags[:20],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": cfg.privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", resumable=True,
                            chunksize=8 * 1024 * 1024)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response, attempt = None, 0
    while response is None:
        try:
            status, response = req.next_chunk()
            if status:
                log.info("Upload %d%%", int(status.progress() * 100))
        except RefreshError as error:
            raise RuntimeError(_refresh_error_message(error)) from error
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and attempt < 5:
                attempt += 1
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(_http_error_message(e)) from e
    vid = response["id"]
    log.info("Uploaded: https://youtu.be/%s (%s)", vid, cfg.privacy_status)
    return vid


def _main() -> int:
    import argparse
    import logging

    from . import config

    parser = argparse.ArgumentParser(
        description="Validate YouTube upload credentials without uploading.")
    parser.add_argument("--verify", action="store_true",
                        help="refresh the OAuth token and confirm channel access")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not args.verify:
        parser.error("nothing to do; pass --verify")
    verify(config.load())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
