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
    niche: str = field(default_factory=lambda: _env("NICHE", "surprising science and history facts"))
    language: str = field(default_factory=lambda: _env("LANGUAGE", "English"))
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "en-US-AndrewNeural"))
    tts_rate: str = field(default_factory=lambda: _env("TTS_RATE", "+0%"))
    target_seconds: int = field(default_factory=lambda: int(_env("TARGET_SECONDS", "45")))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash"))

    # video
    width: int = 1080
    height: int = 1920
    fps: int = 30
    caption_font: str = field(default_factory=lambda: _env("CAPTION_FONT", "DejaVu Sans"))
    caption_size: int = field(default_factory=lambda: int(_env("CAPTION_SIZE", "84")))
    caption_upper: bool = field(default_factory=lambda: _bool("CAPTION_UPPER", True))
    segment_seconds: float = field(default_factory=lambda: float(_env("SEGMENT_SECONDS", "4.5")))

    # keys
    gemini_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    pexels_key: str = field(default_factory=lambda: _env("PEXELS_API_KEY"))
    yt_client_id: str = field(default_factory=lambda: _env("YT_CLIENT_ID"))
    yt_client_secret: str = field(default_factory=lambda: _env("YT_CLIENT_SECRET"))
    yt_refresh_token: str = field(default_factory=lambda: _env("YT_REFRESH_TOKEN"))

    # behaviour
    upload: bool = field(default_factory=lambda: _bool("UPLOAD", False))
    privacy_status: str = field(default_factory=lambda: _env("PRIVACY_STATUS", "private"))
    use_omni: bool = field(default_factory=lambda: _bool("USE_OMNI", False))
    omni_key: str = field(default_factory=lambda: _env("OMNI_API_KEY"))
    omni_hook_seconds: float = field(default_factory=lambda: float(_env("OMNI_HOOK_SECONDS", "6")))

    # paths
    output_dir: Path = ROOT / "output"
    work_dir: Path = ROOT / "work"
    hooks_dir: Path = ROOT / "hooks"
    history_file: Path = ROOT / "data" / "history.json"

    @property
    def can_upload(self) -> bool:
        return bool(self.yt_client_id and self.yt_client_secret and self.yt_refresh_token)


def load() -> Config:
    return Config()
