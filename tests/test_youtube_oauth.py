import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from creatorthon_store import delete_youtube_connection, get_youtube_connection, save_youtube_connection
from youtube_oauth import authorization_url, decrypt_refresh_token, encrypt_refresh_token


class YouTubeOAuthTests(unittest.TestCase):
    def test_refresh_token_is_encrypted_and_round_trips(self):
        with patch.dict(os.environ, {"YOUTUBE_TOKEN_ENCRYPTION_KEY": "test-encryption-secret"}, clear=False):
            encrypted = encrypt_refresh_token("refresh-token-value")
            self.assertNotIn("refresh-token-value", encrypted)
            self.assertEqual(decrypt_refresh_token(encrypted), "refresh-token-value")

    def test_authorization_requests_offline_upload_access(self):
        with patch.dict(os.environ, {"YOUTUBE_CLIENT_ID": "client-id"}, clear=False):
            url = authorization_url("https://example.com/auth/youtube/callback", "signed-state", "me@example.com")
        self.assertIn("youtube.upload", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent+select_account", url)
        self.assertIn("login_hint=me%40example.com", url)

    def test_connection_is_user_scoped_and_deletable(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"APP_DATA_DIR": directory}, clear=False):
            root = Path(directory)
            saved = save_youtube_connection(root, "user-1", {
                "refresh_token_ciphertext": "encrypted",
                "channel_id": "channel-1",
                "channel_title": "My channel",
                "oauth_email": "me@example.com",
            })
            self.assertEqual(saved["channel_title"], "My channel")
            self.assertEqual(get_youtube_connection(root, "user-1")["channel_id"], "channel-1")
            self.assertIsNone(get_youtube_connection(root, "user-2"))
            self.assertTrue(delete_youtube_connection(root, "user-1"))
            self.assertIsNone(get_youtube_connection(root, "user-1"))


if __name__ == "__main__":
    unittest.main()
