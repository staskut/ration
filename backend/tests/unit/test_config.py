"""Settings read from the environment (#59).

`RATION_VERSION` gets a test of its own because losing it is silent: an alert
would say `dev` in production, and the one thing the payload is for — naming a
release somebody can check out and roll back — would be gone with nothing
failing.
"""

from __future__ import annotations

import pytest

from ration.config import settings


@pytest.fixture(autouse=True)
def _fresh_settings() -> None:
    """`settings()` is lru_cached, so each case needs its own read."""
    settings.cache_clear()
    yield
    settings.cache_clear()


class TestTheDeployedVersion:
    def test_it_is_what_the_environment_says(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RATION_VERSION", "a1b2c3d")
        assert settings().service_version == "a1b2c3d"

    def test_it_is_dev_when_nothing_said(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A build that does not know its version should say so, not claim one."""
        monkeypatch.delenv("RATION_VERSION", raising=False)
        assert settings().service_version == "dev"

    def test_it_is_never_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty label is worse than an honest one: it disappears in a query."""
        monkeypatch.setenv("RATION_VERSION", "")
        assert settings().service_version != ""
        assert settings().service_version == "dev"


class TestTelemetryIsOffUnlessAsked:
    def test_off_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RATION_TELEMETRY_ENABLED", raising=False)
        assert settings().telemetry_enabled is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_the_spellings_that_turn_it_on(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        monkeypatch.setenv("RATION_TELEMETRY_ENABLED", value)
        assert settings().telemetry_enabled is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
    def test_anything_else_leaves_it_off(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv("RATION_TELEMETRY_ENABLED", value)
        assert settings().telemetry_enabled is False


class TestTheStagedRelease:
    """#60's unit check. Off by default, so a plain deploy is unchanged.

    It has a test because it was wired wrong once: the field existed, the
    environment said `true`, and `settings()` kept returning False because the
    line that reads it had never been added. Nothing failed — the staged
    incident simply did not happen, which is the hardest kind of bug to see.
    """

    def test_off_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RATION_RESOLVE_PACKAGE_UNITS", raising=False)
        assert settings().resolve_package_units is False

    def test_the_environment_can_turn_it_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RATION_RESOLVE_PACKAGE_UNITS", "true")
        assert settings().resolve_package_units is True
