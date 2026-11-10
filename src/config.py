"""Central configuration. Everything is driven by environment variables so the
same code runs locally and in GitHub Actions."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env(name: str, default: str = "") -> str:
    # GitHub passes unset vars as empty strings; treat those as "use default".
    return os.getenv(name) or default


@dataclass(frozen=True)
class Config:
    # content
    niche: str = field(default_factory=lambda: _env(
        "NICHE", "Funny 3D animated short stories with cute characters (cute babies, funny cats, mischievous pets) in entertaining comedy situations"))
    language: str = field(default_factory=lambda: _env("LANGUAGE", "Hinglish"))
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "hi-IN-MadhurNeural"))
    tts_rate: str = field(default_factory=lambda: _env("TTS_RATE", "+0%"))
    target_seconds: int = field(default_factory=lambda: int(_env("TARGET_SECONDS", "45")))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3.1-flash-lite"))
    # Video model used by the Gemini Interactions (Omni) API. Overridable so a
    # project can switch to another supported model without a code change.
    omni_model: str = field(default_factory=lambda: _env("OMNI_MODEL", "gemini-omni-1.2-flash"))
    # Model used for thumbnail generation (Gemini image generation / nano banana).
    thumbnail_model: str = field(default_factory=lambda: _env("THUMBNAIL_MODEL", "gemini-2.0-flash-exp"))

    # video
    width: int = 1080
    height: int = 1920
    fps: int = 30
    layout: str = field(default_factory=lambda: _env("LAYOUT", "fullscreen"))  # 'fullscreen' or 'frame'
    caption_font: str = field(default_factory=lambda: _env("CAPTION_FONT", "DejaVu Sans"))
    caption_size: int = field(default_factory=lambda: int(_env("CAPTION_SIZE", "78")))
    caption_upper: bool = field(default_factory=lambda: _bool("CAPTION_UPPER", False))
    segment_seconds: float = field(default_factory=lambda: float(_env("SEGMENT_SECONDS", "4.5")))
    # Fixed header text is no longer rendered; only captions appear over the video.
    yt_category_id: str = field(default_factory=lambda: _env("YT_CATEGORY_ID", "23"))

    # Email notifications (Gmail SMTP)
    gmail_address: str = field(default_factory=lambda: _env("GMAIL_ADDRESS"))
    gmail_app_password: str = field(default_factory=lambda: _env("GMAIL_APP_PASSWORD"))
    notify_email: str = field(default_factory=lambda: _env("NOTIFY_EMAIL"))

    @property
    def frame_size(self) -> int:
        return min(int(self.width * 5 / 6), int(self.height * 0.47))

    @property
    def frame_x(self) -> int:
        return (self.width - self.frame_size) // 2

    @property
    def frame_y(self) -> int:
        return (self.height - self.frame_size) // 2

    # keys
    gemini_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    json2video_key: str = field(default_factory=lambda: _env("JSON2VIDEO_API_KEY"))
    # Gemini is the default; JSON2Video must be chosen explicitly so that merely
    # adding a JSON2VIDEO_API_KEY cannot silently switch the channel away from
    # prompt-generated animation to a single still-image render.
    video_provider: str = field(default_factory=lambda: _env("VIDEO_PROVIDER", "gemini"))
    # No default image: a still-image render needs an explicit, on-brand image.
    json2video_image_url: str = field(default_factory=lambda: _env("JSON2VIDEO_IMAGE_URL"))
    yt_client_id: str = field(default_factory=lambda: _env("YT_CLIENT_ID"))
    yt_client_secret: str = field(default_factory=lambda: _env("YT_CLIENT_SECRET"))
    yt_refresh_token: str = field(default_factory=lambda: _env("YT_REFRESH_TOKEN"))

    # behaviour
    upload: bool = field(default_factory=lambda: _bool("UPLOAD", False))
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", False))
    privacy_status: str = field(default_factory=lambda: _env("PRIVACY_STATUS", "private"))
    ai_video_key: str = field(default_factory=lambda: _env("OMNI_API_KEY", _env("GEMINI_API_KEY")))
    ai_video_max_usd: float = field(default_factory=lambda: float(_env("AI_VIDEO_MAX_USD", "3.25")))

    # paths
    output_dir: Path = ROOT / "output"
    work_dir: Path = ROOT / "work"
    history_file: Path = ROOT / "data" / "history.json"

    def __post_init__(self) -> None:
        if not 30 <= self.target_seconds <= 60:
            raise ValueError("TARGET_SECONDS must be between 30 and 60")
        if self.video_provider not in {"gemini", "json2video"}:
            raise ValueError("VIDEO_PROVIDER must be 'gemini' or 'json2video'")
        if self.layout not in {"fullscreen", "frame"}:
            raise ValueError("LAYOUT must be 'fullscreen' or 'frame'")
        if self.privacy_status not in {"private", "unlisted", "public"}:
            raise ValueError(
                "PRIVACY_STATUS must be 'private', 'unlisted', or 'public'")
        if self.ai_video_max_usd < 0:
            raise ValueError("AI_VIDEO_MAX_USD must be zero or greater")

    @property
    def can_upload(self) -> bool:
        return bool(self.yt_client_id and self.yt_client_secret and self.yt_refresh_token)


def load() -> Config:
    return Config()
