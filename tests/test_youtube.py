import os

os.environ["DRY_RUN"] = "false"
os.environ.pop("VIDEO_PROVIDER", None)
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from src.config import Config
from src.youtube import (
    _http_error_message,
    _refresh_error_message,
    missing_credentials,
    upload,
    verify,
)


def _cfg(**overrides):
    values = {
        "yt_client_id": "client-id",
        "yt_client_secret": "client-secret",
        "yt_refresh_token": "refresh-token",
    }
    values.update(overrides)
    return Config(**values)


class CredentialTests(unittest.TestCase):
    def test_missing_credentials_reports_every_missing_secret(self):
        cfg = Config(yt_client_id="", yt_client_secret="", yt_refresh_token="")
        self.assertEqual(
            missing_credentials(cfg),
            ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"],
        )

    def test_verify_fails_before_network_when_credentials_are_missing(self):
        with self.assertRaisesRegex(
            RuntimeError, "YT_CLIENT_ID.*YT_CLIENT_SECRET.*YT_REFRESH_TOKEN"
        ):
            verify(Config(yt_client_id="", yt_client_secret="", yt_refresh_token=""))

    def test_expired_refresh_token_message_explains_fix(self):
        message = _refresh_error_message(
            RefreshError("invalid_grant: Token has been expired or revoked.")
        )
        self.assertIn("get_youtube_token.py", message)
        self.assertIn("7 days", message)

    def test_invalid_client_message_points_at_client_secrets(self):
        message = _refresh_error_message(RefreshError("invalid_client"))
        self.assertIn("YT_CLIENT_ID", message)
        self.assertIn("YT_CLIENT_SECRET", message)

    def test_forbidden_message_points_at_api_and_test_user(self):
        error = HttpError(MagicMock(status=403), b'{"error": {"message": "forbidden"}}')
        message = _http_error_message(error)
        self.assertIn("YouTube Data API v3", message)
        self.assertIn("OAuth test user", message)


class VerifyTests(unittest.TestCase):
    @patch("src.youtube.build")
    @patch("src.youtube.Request")
    @patch("src.youtube._credentials")
    def test_verify_refreshes_token_and_returns_channel_title(self, credentials, request, build):
        credentials.return_value.refresh.return_value = None
        build.return_value.channels.return_value.list.return_value.execute.return_value = {
            "items": [{"snippet": {"title": "My Channel"}}],
        }

        self.assertEqual(verify(_cfg()), "My Channel")
        credentials.return_value.refresh.assert_called_once()
        request.assert_called_once()

    @patch("src.youtube.build")
    @patch("src.youtube.Request")
    @patch("src.youtube._credentials")
    def test_verify_maps_expired_refresh_token(self, credentials, request, build):
        credentials.return_value.refresh.side_effect = RefreshError(
            "invalid_grant: Token has been expired or revoked."
        )

        with self.assertRaisesRegex(RuntimeError, "get_youtube_token.py"):
            verify(_cfg())


class UploadTests(unittest.TestCase):
    @patch("src.youtube.MediaFileUpload")
    @patch("src.youtube.build")
    @patch("src.youtube._credentials")
    def test_upload_maps_expired_refresh_token(self, credentials, build, media):
        request = build.return_value.videos.return_value.insert.return_value
        request.next_chunk.side_effect = RefreshError("invalid_grant")

        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "video.mp4"
            video.write_bytes(b"video")
            with self.assertRaisesRegex(RuntimeError, "get_youtube_token.py"):
                upload(_cfg(), video, {"title": "t", "description": "d", "tags": [], "topic": "x"})


if __name__ == "__main__":
    unittest.main()
