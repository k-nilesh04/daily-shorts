"""Send email notifications via Gmail SMTP on pipeline events."""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .config import Config
from .util import log


def _send_email(cfg: Config, subject: str, body: str) -> bool:
    """Send an email via Gmail SMTP. Returns True on success."""
    address = getattr(cfg, "gmail_address", "")
    password = getattr(cfg, "gmail_app_password", "")
    recipient = getattr(cfg, "notify_email", "") or address

    if not address or not password:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = address
    msg["To"] = recipient
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(address, password)
            server.sendmail(address, [recipient], msg.as_string())
        log.info("Email notification sent to %s", recipient)
        return True
    except (smtplib.SMTPException, OSError, TimeoutError) as error:
        log.warning("Email notification failed: %s", error)
        return False


def notify_success(cfg: Config, video: Path, meta: dict, video_id: str | None = None) -> None:
    """Notify that a video was generated (and optionally uploaded)."""
    address = getattr(cfg, "gmail_address", "")
    if not address:
        return
    title = meta.get("title", "Untitled")
    provider = meta.get("video_generation", {}).get("provider", "unknown")
    body = f"Video ready: {title} ({provider})\n"
    if video_id:
        body += f"https://youtu.be/{video_id}\n"
    body += f"File: {video.name}\n"
    subject = f"[Daily Shorts] Video ready: {title}"
    _send_email(cfg, subject, body)


def notify_failure(cfg: Config, error: str, step: str = "") -> None:
    """Notify that the pipeline failed."""
    address = getattr(cfg, "gmail_address", "")
    if not address:
        return
    body = "Pipeline failed"
    if step:
        body += f" at step: {step}"
    body += f"\n\n{error[:1000]}"
    subject = "[Daily Shorts] Pipeline FAILED"
    _send_email(cfg, subject, body)


def notify_dry_run(cfg: Config, video: Path) -> None:
    """Notify that a dry-run completed."""
    address = getattr(cfg, "gmail_address", "")
    if not address:
        return
    body = f"Dry run complete: {video.name}"
    subject = "[Daily Shorts] Dry run complete"
    _send_email(cfg, subject, body)