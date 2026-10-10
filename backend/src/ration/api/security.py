"""Password hashing and session cookies.

Sessions are signed cookies rather than a token in localStorage (HLD AD-8). The
follower's whole interaction budget is about thirty seconds a day, so anything
that signs them out weekly would end the habit; and an HttpOnly cookie is not
readable by injected script.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ration.config import Settings

_hasher = PasswordHasher()

SESSION_SALT = "ration.session.v1"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


# A real hash of an unguessable value. Verifying against this when an account
# does not exist keeps the response time similar to a genuine failed login, so
# timing does not reveal which addresses are registered. A malformed placeholder
# would raise instead of comparing, and give the game away.
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def verify_password(password: str, password_hash: str) -> bool:
    """True only for a matching password. Never raises, whatever the hash is."""
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, ValueError, TypeError):
        # Covers a mismatch, a malformed hash, and the unusable placeholder the
        # seed writes — all of which simply mean "not authenticated".
        return False


@dataclass(frozen=True, slots=True)
class SessionCodec:
    settings: Settings

    def _serializer(self) -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(self.settings.session_secret, salt=SESSION_SALT)

    def issue(self, user_id: str) -> str:
        return self._serializer().dumps({"uid": user_id})

    def read(self, token: str) -> str | None:
        """Return the user id, or None for anything tampered with or expired."""
        try:
            payload = self._serializer().loads(
                token, max_age=self.settings.session_max_age_days * 24 * 3600
            )
        except (BadSignature, SignatureExpired):
            return None
        user_id = payload.get("uid") if isinstance(payload, dict) else None
        return user_id if isinstance(user_id, str) else None
