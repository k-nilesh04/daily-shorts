import os

os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import smtplib
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import Config
from src.notify import _send_email, notify_dry_run, notify_failure, notify_success


class NotifyTests(unittest.TestCase):
    def test_send_returns_false_without_credentials(self):
        cfg = Config(gmail_address="", gmail_app_password="")
        self.assertFalse(_send_email(cfg, "subj", "body"))

    def test_send_returns_true_on_success(self):
        cfg = Config(
            gmail_address="test@gmail.com",
            gmail_app_password="apppass",
            notify_email="recv@example.com",
        )
        with patch("src.notify.smtplib.SMTP") as smtp_mock:
            server = smtp_mock.return_value.__enter__.return_value
            self.assertTrue(_send_email(cfg, "subj", "body"))
            server.login.assert_called_once_with("test@gmail.com", "apppass")
            server.sendmail.assert_called_once()

    def test_send_returns_false_on_smtp_error(self):
        cfg = Config(gmail_address="test@gmail.com", gmail_app_password="apppass")
        with patch("src.notify.smtplib.SMTP", side_effect=smtplib.SMTPException("conn error")):
            self.assertFalse(_send_email(cfg, "subj", "body"))

    def test_notify_skips_when_no_gmail_address(self):
        cfg = Config(gmail_address="", gmail_app_password="")
        with patch("src.notify._send_email") as send_mock:
            notify_success(cfg, Path("video.mp4"), {"title": "T", "script": "s"}, "vid123")
            notify_failure(cfg, "error msg")
            notify_dry_run(cfg, Path("video.mp4"))
            send_mock.assert_not_called()

    def test_notify_success_calls_send(self):
        cfg = Config(gmail_address="test@gmail.com", gmail_app_password="apppass")
        with patch("src.notify._send_email", return_value=True) as send_mock:
            notify_success(cfg, Path("video.mp4"), {"title": "My Video", "script": "s"}, "abc123")
            send_mock.assert_called_once()
            args = send_mock.call_args
            self.assertIn("My Video", args[0][2])
            self.assertIn("abc123", args[0][2])

    def test_notify_failure_calls_send(self):
        cfg = Config(gmail_address="test@gmail.com", gmail_app_password="apppass")
        with patch("src.notify._send_email", return_value=True) as send_mock:
            notify_failure(cfg, "something broke", step="render")
            send_mock.assert_called_once()
            self.assertIn("render", send_mock.call_args[0][2])

    def test_notify_dry_run_calls_send(self):
        cfg = Config(gmail_address="test@gmail.com", gmail_app_password="apppass")
        with patch("src.notify._send_email", return_value=True) as send_mock:
            notify_dry_run(cfg, Path("video.mp4"))
            send_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
