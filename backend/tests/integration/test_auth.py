"""Sign-in, sessions, and the role boundary."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ration.config import SESSION_COOKIE_NAME
from ration.seed.command import PLANNER_EMAIL

pytestmark = pytest.mark.integration


class TestLogin:
    def test_correct_credentials_set_a_session_cookie(self, api: TestClient) -> None:
        response = api.post(
            "/api/auth/login", json={"email": PLANNER_EMAIL, "password": "correct-horse-battery"}
        )
        assert response.status_code == 204
        assert SESSION_COOKIE_NAME in response.cookies

    def test_the_cookie_is_httponly_and_samesite_lax(self, api: TestClient) -> None:
        """HttpOnly keeps injected script from reading it; Lax stops it riding
        along on a cross-site request."""
        response = api.post(
            "/api/auth/login", json={"email": PLANNER_EMAIL, "password": "correct-horse-battery"}
        )
        header = response.headers["set-cookie"].lower()
        assert "httponly" in header
        assert "samesite=lax" in header

    def test_a_wrong_password_is_rejected(self, api: TestClient) -> None:
        response = api.post(
            "/api/auth/login", json={"email": PLANNER_EMAIL, "password": "wrong-password-here"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_an_unknown_account_gives_the_same_answer_as_a_wrong_password(
        self, api: TestClient
    ) -> None:
        """The message must not reveal which addresses have accounts."""
        unknown = api.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "correct-horse-battery"},
        )
        wrong = api.post(
            "/api/auth/login", json={"email": PLANNER_EMAIL, "password": "wrong-password-here"}
        )
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()

    def test_a_malformed_request_is_422_in_the_shared_error_shape(self, api: TestClient) -> None:
        response = api.post("/api/auth/login", json={"email": "not-an-email", "password": "x"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"
        assert response.json()["error"]["details"]


class TestSession:
    def test_me_reports_the_role_and_profile(self, planner: TestClient) -> None:
        body = planner.get("/api/auth/me").json()
        assert body["role"] == "planner"
        assert body["profile_id"]
        assert body["locale"] == "en"

    def test_the_follower_is_told_apart(self, follower: TestClient) -> None:
        assert follower.get("/api/auth/me").json()["role"] == "follower"

    def test_both_roles_share_one_profile(self, planner: TestClient, follower: TestClient) -> None:
        assert (
            planner.get("/api/auth/me").json()["profile_id"]
            == (follower.get("/api/auth/me").json()["profile_id"])
        )

    def test_an_unauthenticated_request_is_401(self, api: TestClient) -> None:
        assert api.get("/api/auth/me").status_code == 401

    def test_logout_clears_the_session(self, planner: TestClient) -> None:
        assert planner.post("/api/auth/logout").status_code == 204
        assert planner.get("/api/auth/me").status_code == 401

    def test_a_tampered_cookie_is_rejected(self, planner: TestClient) -> None:
        """The cookie is signed; editing it must not grant anything."""
        planner.cookies.set(SESSION_COOKIE_NAME, "forged.session.value")
        response = planner.get("/api/auth/me")
        assert response.status_code == 401

    def test_a_cookie_signed_with_another_secret_is_rejected(self, planner: TestClient) -> None:
        from ration.api.security import SessionCodec
        from ration.config import Settings

        other = Settings(
            database_url="sqlite://",
            environment="development",
            session_secret="a-different-secret-entirely",
        )
        planner.cookies.set(SESSION_COOKIE_NAME, SessionCodec(other).issue("anyone"))
        assert planner.get("/api/auth/me").status_code == 401


class TestPasswordHandling:
    def test_passwords_are_never_stored_in_plain_text(self, api: TestClient, engine) -> None:  # type: ignore[no-untyped-def]
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from ration.repositories import models

        with Session(engine) as session:
            hashes = list(session.scalars(select(models.User.password_hash)))
        assert hashes
        for value in hashes:
            assert "correct-horse-battery" not in value
            assert value.startswith("$argon2")

    def test_the_seed_writes_an_unusable_placeholder_hash(self, engine) -> None:  # type: ignore[no-untyped-def]
        """An unseeded deployment must not ship with working credentials."""
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from ration.api.security import verify_password
        from ration.repositories import models
        from ration.seed.command import DEV_PASSWORD_HASH_PLACEHOLDER, seed

        seed(engine)
        with Session(engine) as session:
            stored = session.scalars(select(models.User.password_hash)).first()
        assert stored == DEV_PASSWORD_HASH_PLACEHOLDER
        assert verify_password("anything at all", DEV_PASSWORD_HASH_PLACEHOLDER) is False


class TestHealth:
    def test_health_needs_no_session(self, api: TestClient) -> None:
        body = api.get("/health").json()
        assert body["status"] == "ok"

    def test_health_names_the_release_it_is_serving(self, api: TestClient) -> None:
        """#59: the only way to ask a deployed environment what it runs.

        A Fly machine ships no telemetry yet (#62), and an alert that names a
        release is worth nothing if the release cannot be checked. "dev" when
        the build was not told — never empty, never absent.
        """
        body = api.get("/health").json()
        assert body["version"]
        assert set(body) == {"status", "version"}


class TestDemoSignIn:
    """One-click entry for the public demo, and the one thing that stops it.

    The guard is not "is this endpoint enabled" but "did the seed run here",
    which is the same question the seed already refuses to answer in
    production. Restating the refusal is what keeps the two from drifting.
    """

    def test_a_seeded_deployment_offers_both_roles(self, api: TestClient) -> None:
        response = api.get("/api/auth/demo")
        assert response.status_code == 200
        assert response.json() == {"available": True, "roles": ["follower", "planner"]}

    def test_signing_in_as_the_planner_needs_no_password(self, api: TestClient) -> None:
        response = api.post("/api/auth/demo", json={"role": "planner"})
        assert response.status_code == 204
        assert SESSION_COOKIE_NAME in response.cookies

        me = api.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["role"] == "planner"

    def test_signing_in_as_the_follower_lands_on_the_follower(self, api: TestClient) -> None:
        assert api.post("/api/auth/demo", json={"role": "follower"}).status_code == 204
        assert api.get("/api/auth/me").json()["role"] == "follower"

    def test_an_unknown_role_is_refused_before_it_reaches_the_database(
        self, api: TestClient
    ) -> None:
        assert api.post("/api/auth/demo", json={"role": "admin"}).status_code == 422

    def test_production_offers_no_demo(
        self, api: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The accounts exist in this database — the fixture seeded them. The
        # refusal has to come from the environment rather than from their
        # absence, because a production database that somehow holds a demo
        # account is exactly the case where this must not hand out a session.
        #
        # Driven through the real environment variable rather than a patched
        # dependency, so what is under test is the same chain production runs:
        # RATION_ENV to Settings.is_production to the refusal.
        from ration.config import settings

        monkeypatch.setenv("RATION_ENV", "production")
        monkeypatch.setenv("RATION_SESSION_SECRET", "x" * 43)
        settings.cache_clear()
        try:
            assert api.get("/api/auth/demo").json() == {"available": False, "roles": []}
            assert api.post("/api/auth/demo", json={"role": "planner"}).status_code == 403
        finally:
            settings.cache_clear()
