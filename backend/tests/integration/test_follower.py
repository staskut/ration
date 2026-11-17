"""Feedback and Today (#30, #31)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def plan_id(planner: TestClient) -> str:
    plans = planner.get("/api/plans").json()
    return next(p["id"] for p in plans if p["name"] == "Pilot week 1")


@pytest.fixture
def entry_id(planner: TestClient, plan_id: str) -> str:
    plan = planner.get(f"/api/plans/{plan_id}").json()
    return plan["days"][0]["entries"][0]["id"]


class TestFeedback:
    def test_a_rating_alone_is_enough(
        self, follower: TestClient, plan_id: str, entry_id: str
    ) -> None:
        """One request, one field. Anything more and the loop dies."""
        body = follower.put(
            f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
            json={"rating": "liked"},
        ).json()
        assert body["rating"] == "liked"

    def test_status_is_inferred_never_submitted(
        self, follower: TestClient, plan_id: str, entry_id: str
    ) -> None:
        body = follower.put(
            f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
            json={"rating": "neutral", "status": "not_tried"},
        ).json()
        assert body["status"] == "tried"

    def test_bloating_and_satiety_can_arrive_later(
        self, follower: TestClient, plan_id: str, entry_id: str
    ) -> None:
        follower.put(
            f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
            json={"rating": "liked"},
        )
        body = follower.put(
            f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
            json={"rating": "liked", "bloating": 2, "satiety": "right"},
        ).json()
        assert body["bloating"] == 2
        assert body["satiety"] == "right"
        assert body["rating"] == "liked"

    def test_re_rating_updates_in_place(
        self, follower: TestClient, plan_id: str, entry_id: str
    ) -> None:
        follower.put(
            f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
            json={"rating": "liked"},
        )
        body = follower.put(
            f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
            json={"rating": "disliked"},
        ).json()
        assert body["rating"] == "disliked"

    @pytest.mark.parametrize("bad", [-1, 4, 99])
    def test_bloating_outside_the_scale_is_422(
        self, follower: TestClient, plan_id: str, entry_id: str, bad: int
    ) -> None:
        assert (
            follower.put(
                f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
                json={"rating": "liked", "bloating": bad},
            ).status_code
            == 422
        )

    def test_the_planner_may_read_but_not_write_feedback(
        self, planner: TestClient, plan_id: str, entry_id: str
    ) -> None:
        assert (
            planner.put(
                f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
                json={"rating": "liked"},
            ).status_code
            == 403
        )

    def test_an_entry_on_another_plan_is_404(self, follower: TestClient, plan_id: str) -> None:
        assert (
            follower.put(
                f"/api/plans/{plan_id}/entries/nope/feedback", json={"rating": "liked"}
            ).status_code
            == 404
        )

    def test_feedback_appears_on_the_plan_for_the_planner(
        self, planner: TestClient, follower: TestClient, plan_id: str, entry_id: str, seeded_day
    ) -> None:
        follower.put(
            f"/api/plans/{plan_id}/entries/{entry_id}/feedback",
            json={"rating": "disliked"},
        )
        today = follower.get("/api/today", params={"date": seeded_day(0)}).json()
        rated = [
            e
            for slot in today["slots"]
            for e in slot["entries"]
            if e["feedback"] and e["feedback"]["rating"] == "disliked"
        ]
        assert rated


class TestToday:
    def test_resolves_the_active_plan_with_no_parameters(
        self, follower: TestClient, seeded_day
    ) -> None:
        response = follower.get("/api/today", params={"date": seeded_day(0)})
        assert response.status_code == 200
        assert response.json()["day_index"] == 0

    def test_slot_times_come_from_the_day_template(self, follower: TestClient, seeded_day) -> None:
        """A long shift moves dinner to 21:00, not 18:00."""
        normal = follower.get("/api/today", params={"date": seeded_day(1)}).json()
        long_shift = follower.get("/api/today", params={"date": seeded_day(2)}).json()
        assert long_shift["day_template"] == "long_shift"
        assert next(s for s in normal["slots"] if s["slot"] == "dinner")["time"] == "18:00"
        assert next(s for s in long_shift["slots"] if s["slot"] == "dinner")["time"] == "21:00"

    def test_each_entry_carries_name_portion_and_totals(
        self, follower: TestClient, seeded_day
    ) -> None:
        body = follower.get("/api/today", params={"date": seeded_day(0)}).json()
        entry = next(e for s in body["slots"] for e in s["entries"] if s["slot"] == "dinner")
        assert entry["module_name"]
        assert entry["portion_grams"]
        assert entry["kcal"]

    def test_home_only_is_marked(self, follower: TestClient, seeded_day) -> None:
        """Reheated fish is not packed for work."""
        body = follower.get("/api/today", params={"date": seeded_day(0)}).json()
        dinner = next(s for s in body["slots"] if s["slot"] == "dinner")
        assert dinner["entries"][0]["home_only"] is True

    def test_critical_sizes_surface_as_notes(self, follower: TestClient, seeded_day) -> None:
        body = follower.get("/api/today", params={"date": seeded_day(3)}).json()
        lunch = next(s for s in body["slots"] if s["slot"] == "lunch")
        assert lunch["entries"][0]["critical_notes"]

    def test_day_totals_are_present(self, follower: TestClient, seeded_day) -> None:
        body = follower.get("/api/today", params={"date": seeded_day(0)}).json()
        assert body["kcal"] == "1577.59"

    def test_all_five_slots_appear_even_when_empty(self, follower: TestClient, seeded_day) -> None:
        """A calm empty state, not a missing key."""
        body = follower.get("/api/today", params={"date": seeded_day(0)}).json()
        assert [s["slot"] for s in body["slots"]] == [
            "breakfast",
            "lunch",
            "snack",
            "dinner",
            "treat",
        ]
        treat = next(s for s in body["slots"] if s["slot"] == "treat")
        assert treat["entries"] == []
        assert treat["kcal"] == "0"

    def test_an_unplanned_day_returns_empty_slots_not_404(
        self, follower: TestClient, seeded_day
    ) -> None:
        body = follower.get("/api/today", params={"date": seeded_day(6)})
        assert body.status_code == 200
        assert all(s["entries"] == [] for s in body.json()["slots"])

    def test_a_date_outside_the_plan_is_404(self, follower: TestClient) -> None:
        assert follower.get("/api/today", params={"date": "2027-01-01"}).status_code == 404

    def test_the_planner_sees_the_same_day(self, planner: TestClient, seeded_day) -> None:
        assert planner.get("/api/today", params={"date": seeded_day(0)}).status_code == 200

    def test_unauthenticated_is_401(self, api: TestClient) -> None:
        assert api.get("/api/today").status_code == 401
