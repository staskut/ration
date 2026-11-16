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
    telemetry_enabled: bool = False
    otlp_endpoint: str = "http://localhost:4318"
    service_name: str = "ration-api"
    # What release is running. Carried as the `service.version` resource
    # attribute, which is how it reaches the metrics and, through them, the
    # alert payload (HLD 7). "dev" is honest about an unset value: a build
    # that does not know its own version should say so rather than claim one.
    service_version: str = "dev"

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
        # Off unless asked for. HLD 6: off locally, on under Compose, staging
        # and production. A default of on would send a developer's local
        # traffic at an endpoint that is not there.
        telemetry_enabled=_flag("RATION_TELEMETRY_ENABLED"),
        otlp_endpoint=os.environ.get("RATION_OTLP_ENDPOINT", "http://localhost:4318"),
        service_name=os.environ.get("RATION_SERVICE_NAME", "").strip() or "ration-api",
        # An empty value falls back rather than through. A deploy pipeline
        # that computes the version into a variable and gets nothing would
        # otherwise label every series with "", which disappears in a query
        # and takes the alert's one actionable field with it.
        service_version=os.environ.get("RATION_VERSION", "").strip() or "dev",
    )


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
