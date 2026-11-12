import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from email_auth import EmailAuthError, authenticate_email_account, create_email_account, email_session_token, read_email_session


class EmailAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.environment = patch.dict(
            os.environ,
            {"DATABASE_URL": "", "APP_DATA_DIR": str(self.root / "data"), "EMAIL_SESSION_SECRET": "test-session-secret-long-enough"},
            clear=False,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def test_customer_can_create_account_and_sign_in(self):
        account = create_email_account(self.root, "Customer@Example.com", "correct-horse-battery")
        self.assertEqual(account["email"], "customer@example.com")
        authenticated = authenticate_email_account(self.root, "customer@example.com", "correct-horse-battery")
        self.assertEqual(authenticated["id"], account["id"])

    def test_password_is_not_stored_or_returned(self):
        account = create_email_account(self.root, "secure@example.com", "private-password-123")
        self.assertNotIn("password_hash", account)
        self.assertIsNone(authenticate_email_account(self.root, "secure@example.com", "wrong-password"))

    def test_duplicate_email_and_short_password_are_rejected(self):
        with self.assertRaises(EmailAuthError):
            create_email_account(self.root, "short@example.com", "short")
        create_email_account(self.root, "same@example.com", "first-password-123")
        with self.assertRaises(EmailAuthError):
            create_email_account(self.root, "SAME@example.com", "second-password-123")

    def test_signed_session_preserves_tenant_identity(self):
        account = create_email_account(self.root, "tenant@example.com", "tenant-password-123")
        payload = read_email_session(email_session_token(account))
        self.assertEqual(payload["sub"], f"email:{account['id']}")
        self.assertEqual(payload["email"], "tenant@example.com")
        self.assertIsNone(read_email_session(email_session_token(account) + "tampered"))


if __name__ == "__main__":
    unittest.main()
