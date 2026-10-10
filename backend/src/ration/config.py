"""Configuration from the environment. No secrets in the image."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache

SESSION_COOKIE_NAME = "ration_session"


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    environment: str
    session_secret: str
    session_max_age_days: int = 90

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookies_require_https(self) -> bool:
        """Secure cookies everywhere but local development, where there is no TLS."""
        return self.environment != "development"


@lru_cache
def settings() -> Settings:
    environment = os.environ.get("RATION_ENV", "development")
    secret = os.environ.get("RATION_SESSION_SECRET")

    if secret is None:
        if environment == "production":
            raise RuntimeError(
                "RATION_SESSION_SECRET must be set in production. A generated key "
                "would change on every restart and sign out every session."
            )
        # Development and tests get an ephemeral key rather than a committed
        # default, so a hardcoded secret can never reach a deployed environment.
        secret = secrets.token_urlsafe(32)

    return Settings(
        database_url=os.environ.get("RATION_DATABASE_URL", "sqlite:///./ration.db"),
        environment=environment,
        session_secret=secret,
        session_max_age_days=int(os.environ.get("RATION_SESSION_DAYS", "90")),
    )
