"""The main workflows end to end at the API level (#34).

These build state through the API rather than inserting rows, so they exercise
the contract rather than the schema. A test that seeds the database directly
can pass while the endpoint that is supposed to create that state is broken.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded_plan(planner: TestClient) -> str:
    plans = planner.get("/api/plans").json()
    return next(p["id"] for p in plans if p["name"] == "Пилотная неделя 1")


class TestBuildingAWeekFromNothing:
    def test_a_week_can_be_built_through_the_api_alone(self, planner: TestClient) -> None:
        """Create a plan, set templates, fill slots, and end with a usable week."""
        plan = planner.post(
            "/api/plans", json={"name": "С нуля", "start_date": "2026-11-23"}
        ).json()
        plan_id = plan["id"]
        assert len(plan["days"]) == 7

        planner.put(f"/api/plans/{plan_id}/days/0", json={"day_template": "training"})
        planner.put(f"/api/plans/{plan_id}/days/2", json={"day_template": "long_shift"})

        for day in range(3):
            for slot, module in (
                ("breakfast", "cottage_cheese_box"),
                ("lunch", "lunch_rice_noodles_turkey"),
                ("snack", "snack_banana_nuts"),
                ("dinner", "dinner_shrimp_asian"),
            ):
                response = planner.post(
                    f"/api/plans/{plan_id}/days/{day}/entries",
                    json={"slot": slot, "module_id": module},
                )
                assert response.status_code == 201, response.text

        built = planner.get(f"/api/plans/{plan_id}").json()
        assert sum(len(d["entries"]) for d in built["days"]) == 12
        assert built["days"][0]["day_template"] == "training"
        assert built["days"][0]["kcal"] != "0"

    def test_the_built_week_produces_a_shopping_list_and_a_prep_plan(
        self, planner: TestClient
    ) -> None:
        plan_id = planner.post(
            "/api/plans", json={"name": "Со списком", "start_date": "2026-11-30"}
        ).json()["id"]
        for day in range(3):
            planner.post(
                f"/api/plans/{plan_id}/days/{day}/entries",
                json={"slot": "lunch", "module_id": "lunch_rice_noodles_turkey"},
            )

        shopping = planner.get(f"/api/plans/{plan_id}/shopping-list").json()
        turkey = next(x for x in shopping["lines"] if x["ingredient_id"] == "turkey_thigh")
        # Three lunches at 120 g cooked, divided by a 0.65 yield.
        assert turkey["needed_raw_g"] == "553.8"

        prep = planner.get(f"/api/plans/{plan_id}/prep-plan").json()
        assert len(prep) == 1
        assert prep[0]["portions"] == 3


class TestCopyingAWeek:
    def test_a_copy_reproduces_the_source(self, planner: TestClient, seeded_plan: str) -> None:
        copy = planner.post(
            "/api/plans",
            json={"name": "Копия", "start_date": "2026-12-28", "copy_from_plan_id": seeded_plan},
        ).json()
        source = planner.get(f"/api/plans/{seeded_plan}").json()
        assert [[e["module_id"] for e in d["entries"]] for d in copy["days"]] == [
            [e["module_id"] for e in d["entries"]] for d in source["days"]
        ]

    def test_the_copy_validates_the_same_way(self, planner: TestClient, seeded_plan: str) -> None:
        copy_id = planner.post(
            "/api/plans",
            json={"name": "Копия 2", "start_date": "2027-01-04", "copy_from_plan_id": seeded_plan},
        ).json()["id"]
        source = planner.get(f"/api/plans/{seeded_plan}/validation").json()
        copy = planner.get(f"/api/plans/{copy_id}/validation").json()
        assert copy["error_count"] == source["error_count"]
        assert copy["warning_count"] == source["warning_count"]


class TestRulesFireThroughTheApi:
    def test_a_fourth_treat_reports_frequency_exceeded(
        self, planner: TestClient, seeded_plan: str
    ) -> None:
        body = planner.post(
            f"/api/plans/{seeded_plan}/days/0/entries",
            json={"slot": "treat", "module_id": "treat_ice_cream"},
        ).json()
        assert "FREQUENCY_EXCEEDED" in [f["code"] for f in body["validation"]["findings"]]

    def test_wine_on_a_training_day_reports_a_template_gate(
        self, planner: TestClient, seeded_plan: str
    ) -> None:
        body = planner.put(
            f"/api/plans/{seeded_plan}/days/1", json={"day_template": "training"}
        ).json()
        assert "TEMPLATE_GATE_VIOLATED" in [f["code"] for f in body["validation"]["findings"]]

    def test_excluding_an_ingredient_the_plan_uses_reports_it(
        self, planner: TestClient, seeded_plan: str
    ) -> None:
        profile_id = planner.get("/api/auth/me").json()["profile_id"]
        planner.put(
            f"/api/profiles/{profile_id}/ingredient-rules",
            json=[{"ingredient_id": "spinach", "rule": "excluded"}],
        )
        codes = [
            f["code"]
            for f in planner.get(f"/api/plans/{seeded_plan}/validation").json()["findings"]
        ]
        assert "EXCLUDED_INGREDIENT" in codes


class TestTheTwoPersonLoop:
    def test_the_follower_rates_and_the_planner_sees_it(
        self, planner: TestClient, follower: TestClient, seeded_plan: str
    ) -> None:
        entry = planner.get(f"/api/plans/{seeded_plan}").json()["days"][0]["entries"][0]
        follower.put(
            f"/api/plans/{seeded_plan}/entries/{entry['id']}/feedback",
            json={"rating": "disliked", "note": "слишком много"},
        )
        today = planner.get("/api/today", params={"date": "2026-10-12"}).json()
        rated = [
            e
            for s in today["slots"]
            for e in s["entries"]
            if e["feedback"] and e["feedback"]["rating"] == "disliked"
        ]
        assert rated
        assert rated[0]["feedback"]["note"] == "слишком много"

    def test_check_off_state_crosses_between_the_two(
        self, planner: TestClient, follower: TestClient, seeded_plan: str
    ) -> None:
        follower.patch(f"/api/plans/{seeded_plan}/shopping-list/banana", json={"checked": True})
        lines = planner.get(f"/api/plans/{seeded_plan}/shopping-list").json()["lines"]
        assert next(x for x in lines if x["ingredient_id"] == "banana")["checked"]

    def test_a_planner_change_shows_on_the_followers_today(
        self, planner: TestClient, follower: TestClient, seeded_plan: str
    ) -> None:
        before = follower.get("/api/today", params={"date": "2026-10-18"}).json()
        assert all(s["entries"] == [] for s in before["slots"])

        planner.post(
            f"/api/plans/{seeded_plan}/days/6/entries",
            json={"slot": "dinner", "module_id": "dinner_squid_pepper"},
        )
        after = follower.get("/api/today", params={"date": "2026-10-18"}).json()
        dinner = next(s for s in after["slots"] if s["slot"] == "dinner")
        assert dinner["entries"][0]["module_id"] == "dinner_squid_pepper"


class TestCorrectingTheCatalogPropagates:
    def test_an_ingredient_correction_changes_the_plan_and_the_shopping_list(
        self, planner: TestClient, seeded_plan: str
    ) -> None:
        """The reason totals are computed and never stored."""
        before_day = planner.get(f"/api/plans/{seeded_plan}").json()["days"][0]["kcal"]
        before_raw = next(
            x
            for x in planner.get(f"/api/plans/{seeded_plan}/shopping-list").json()["lines"]
            if x["ingredient_id"] == "white_fish"
        )["needed_raw_g"]

        planner.patch(
            "/api/ingredients/white_fish",
            json={"kcal_per_100g": "205", "yield_factor": "0.6"},
        )

        after_day = planner.get(f"/api/plans/{seeded_plan}").json()["days"][0]["kcal"]
        after_raw = next(
            x
            for x in planner.get(f"/api/plans/{seeded_plan}/shopping-list").json()["lines"]
            if x["ingredient_id"] == "white_fish"
        )["needed_raw_g"]

        assert after_day != before_day
        assert after_raw != before_raw
