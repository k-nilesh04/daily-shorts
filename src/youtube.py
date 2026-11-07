"""Step 5 - upload to YouTube with the Data API v3 (OAuth refresh token)."""
import time
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

from .config import Config
from .util import log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def upload(cfg: Config, video: Path, meta: dict) -> str:
    creds = Credentials(
        token=None,
        refresh_token=cfg.yt_refresh_token,
        token_uri=TOKEN_URI,
        client_id=cfg.yt_client_id,
        client_secret=cfg.yt_client_secret,
        scopes=SCOPES,
    )
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
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and attempt < 5:
                attempt += 1
                time.sleep(2 ** attempt)
                continue
            raise
    vid = response["id"]
    log.info("Uploaded: https://youtu.be/%s (%s)", vid, cfg.privacy_status)
    return vid
