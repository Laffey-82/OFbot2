from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime


class PasswordHasher:
    ITERATIONS = 600_000

    def hash_password(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, self.ITERATIONS
        )
        return f"pbkdf2_sha256${self.ITERATIONS}${salt.hex()}${digest.hex()}"

    def needs_upgrade(self, encoded: str) -> bool:
        try:
            _, iterations, _, _ = encoded.split("$", 3)
            return int(iterations) < self.ITERATIONS
        except Exception:
            return False

    def verify_password(self, password: str, encoded: str) -> bool:
        try:
            algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, int(iterations)
            )
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False


def make_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def make_session_id() -> str:
    return secrets.token_urlsafe(32)


def utcnow() -> datetime:
    return datetime.now(UTC)


password_hasher = PasswordHasher()
