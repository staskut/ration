"""Configuration from the environment. No secrets in the image."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    environment: str

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def settings() -> Settings:
    return Settings(
        database_url=os.environ.get("RATION_DATABASE_URL", "sqlite:///./ration.db"),
        environment=os.environ.get("RATION_ENV", "development"),
    )
