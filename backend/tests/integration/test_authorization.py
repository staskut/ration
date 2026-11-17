"""The role boundary across every route, not a sample of them (#33).

The route list is derived from the application rather than hand-maintained, so
a new endpoint is covered the moment it is added. A hand-written list is the
thing that goes stale, and a stale authorisation test is worse than none —
it reports coverage it does not have.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

# Mutations both roles may perform. Mirrors the allowlist in the contract test;
# anything not named here must be able to answer 403 to a follower.
OPEN_TO_BOTH_ROLES = {
    "login",  # public; anyone may attempt it
    "logout",
    "setShoppingItemChecked",  # the follower is the one in the shop
    "setFeedback",  # follower-only, checked separately below
}

# Routes a follower may read. Everything else planner-only on reads would make
# Today and the shopping list unusable.
SAMPLE_IDS = {
    "{ingredientId}": "banana",
    "{ingredient_id}": "banana",
    "{moduleId}": "snack_banana_nuts",
    "{module_id}": "snack_banana_nuts",
    "{entryId}": "no-such-entry",
    "{entry_id}": "no-such-entry",
    "{dayIndex}": "0",
    "{day_index}": "0",
}


def routes(app) -> list[tuple[str, str, str]]:  # type: ignore[no-untyped-def]
    """Every API route, as (method, full path, operation id).

    FastAPI wraps an included router in `_IncludedRouter`, and the real routes
    inside carry a router-relative path — the `/api` prefix lives on the
    include context. Reading `route.path` alone yields `/auth/login` and
    matches nothing, which is the mistake `test_the_route_list_is_not_empty`
    exists to catch.
    """
    found: list[tuple[str, str, str]] = []
    _collect(app.routes, "", found)
    return sorted({r for r in found if r[1].startswith("/api")})


def _collect(items, prefix: str, found: list) -> None:  # type: ignore[no-untyped-def]
    for item in items:
        inner = getattr(item, "original_router", None)
        if inner is not None:
            context = getattr(item, "include_context", None)
            _collect(inner.routes, prefix + getattr(context, "prefix", ""), found)
            continue
        if isinstance(item, APIRoute):
            for method in sorted(item.methods - {"HEAD", "OPTIONS"}):
                found.append((method, prefix + item.path, item.operation_id or ""))


def concrete(path: str, plan_id: str, profile_id: str) -> str:
    path = path.replace("{planId}", plan_id).replace("{plan_id}", plan_id)
    path = path.replace("{profileId}", profile_id).replace("{profile_id}", profile_id)
    for token, value in SAMPLE_IDS.items():
        path = path.replace(token, value)
    return path


@pytest.fixture
def ids(planner: TestClient) -> dict[str, str]:
    plans = planner.get("/api/plans").json()
    return {
        "plan": next(p["id"] for p in plans if p["name"] == "Pilot week 1"),
        "profile": planner.get("/api/auth/me").json()["profile_id"],
    }


def test_the_route_list_is_not_empty(planner: TestClient) -> None:
    """Guards the derivation itself: a broken walker would silently pass
    every parameterised test below by iterating nothing."""
    assert len(routes(planner.app)) >= 25


class TestUnauthenticated:
    def test_every_protected_route_rejects_an_anonymous_caller(
        self, anonymous: TestClient, planner: TestClient, ids: dict[str, str]
    ) -> None:
        allowed_without_a_session = {"login"}
        failures = []
        for method, path, operation in routes(planner.app):
            if operation in allowed_without_a_session:
                continue
            url = concrete(path, ids["plan"], ids["profile"])
            response = anonymous.request(method, url, json={})
            if response.status_code != 401:
                failures.append(f"{method} {path} -> {response.status_code}")
        assert failures == []


class TestFollowerBoundary:
    def test_every_planner_only_mutation_rejects_a_follower(
        self, follower: TestClient, planner: TestClient, ids: dict[str, str]
    ) -> None:
        failures = []
        for method, path, operation in routes(planner.app):
            if method == "GET" or operation in OPEN_TO_BOTH_ROLES:
                continue
            url = concrete(path, ids["plan"], ids["profile"])
            response = follower.request(method, url, json={})
            # 403 is the answer. A 404 or 422 would mean the request was
            # rejected for the wrong reason and the role check never ran.
            if response.status_code != 403:
                failures.append(f"{method} {path} ({operation}) -> {response.status_code}")
        assert failures == []

    def test_a_follower_can_read_what_the_screens_need(
        self, follower: TestClient, ids: dict[str, str], seeded_day
    ) -> None:
        for path in (
            "/api/ingredients",
            "/api/modules",
            f"/api/profiles/{ids['profile']}",
            f"/api/plans/{ids['plan']}",
            f"/api/plans/{ids['plan']}/validation",
            f"/api/plans/{ids['plan']}/shopping-list",
            f"/api/plans/{ids['plan']}/prep-plan",
            "/api/today?date=" + seeded_day(0),
        ):
            assert follower.get(path).status_code == 200, path

    def test_a_follower_can_write_only_feedback_and_check_off(
        self, follower: TestClient, planner: TestClient, ids: dict[str, str]
    ) -> None:
        entry = planner.get(f"/api/plans/{ids['plan']}").json()["days"][0]["entries"][0]["id"]
        assert (
            follower.put(
                f"/api/plans/{ids['plan']}/entries/{entry}/feedback", json={"rating": "liked"}
            ).status_code
            == 200
        )
        assert (
            follower.patch(
                f"/api/plans/{ids['plan']}/shopping-list/banana", json={"checked": True}
            ).status_code
            == 200
        )

    def test_the_both_roles_list_names_only_real_operations(self, planner: TestClient) -> None:
        """Stops the allowlist outliving the operations it excuses."""
        known = {operation for _, _, operation in routes(planner.app)}
        assert known >= OPEN_TO_BOTH_ROLES


class TestCrossProfile:
    """Another profile's data is 404, never 403.

    A 403 would confirm the resource exists, which is a disclosure the API has
    no reason to make.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/api/plans/not-mine",
            "/api/plans/not-mine/validation",
            "/api/plans/not-mine/shopping-list",
            "/api/plans/not-mine/prep-plan",
            "/api/profiles/not-mine",
        ],
    )
    def test_reads_are_404(self, planner: TestClient, path: str) -> None:
        assert planner.get(path).status_code == 404

    def test_writes_are_404(self, planner: TestClient) -> None:
        assert planner.patch("/api/plans/not-mine", json={"name": "x"}).status_code == 404
        assert planner.put("/api/profiles/not-mine/slot-budgets", json=[]).status_code == 404
        assert (
            planner.post(
                "/api/plans/not-mine/days/0/entries",
                json={"slot": "dinner", "module_id": "dinner_squid_pepper"},
            ).status_code
            == 404
        )

    def test_an_unknown_ingredient_or_module_is_404_not_500(self, planner: TestClient) -> None:
        assert planner.get("/api/ingredients/ghost").status_code == 404
        assert planner.get("/api/modules/ghost").status_code == 404


class TestSessionHandling:
    def test_a_tampered_cookie_is_rejected(self, planner: TestClient) -> None:
        from ration.config import SESSION_COOKIE_NAME

        planner.cookies.set(SESSION_COOKIE_NAME, "forged.value.here")
        assert planner.get("/api/auth/me").status_code == 401

    def test_a_cookie_signed_with_another_secret_is_rejected(self, planner: TestClient) -> None:
        from ration.api.security import SessionCodec
        from ration.config import SESSION_COOKIE_NAME, Settings

        other = Settings(
            database_url="sqlite://",
            environment="development",
            session_secret="a-completely-different-secret",
        )
        planner.cookies.set(SESSION_COOKIE_NAME, SessionCodec(other).issue("anyone"))
        assert planner.get("/api/auth/me").status_code == 401

    def test_an_expired_session_is_rejected(self, planner: TestClient) -> None:
        from ration.api.security import SessionCodec
        from ration.config import SESSION_COOKIE_NAME, Settings

        expired = Settings(
            database_url="sqlite://",
            environment="development",
            session_secret=__import__("ration.config", fromlist=["settings"])
            .settings()
            .session_secret,
            session_max_age_days=0,
        )
        planner.cookies.set(SESSION_COOKIE_NAME, SessionCodec(expired).issue("anyone"))
        assert planner.get("/api/auth/me").status_code == 401
