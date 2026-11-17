"""Validation, shopping list, check-off and prep plan over HTTP (#28, #29)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def plan_id(planner: TestClient) -> str:
    plans = planner.get("/api/plans").json()
    return next(p["id"] for p in plans if p["name"] == "Pilot week 1")


class TestValidation:
    def test_returns_findings_sorted_errors_first(self, planner: TestClient, plan_id: str) -> None:
        body = planner.get(f"/api/plans/{plan_id}/validation").json()
        levels = [f["level"] for f in body["findings"]]
        assert levels == sorted(levels, key=["error", "warning", "info"].index)

    def test_counts_match_the_findings(self, planner: TestClient, plan_id: str) -> None:
        body = planner.get(f"/api/plans/{plan_id}/validation").json()
        assert body["error_count"] == sum(1 for f in body["findings"] if f["level"] == "error")
        assert body["warning_count"] == sum(1 for f in body["findings"] if f["level"] == "warning")

    def test_the_reference_week_reports_what_the_golden_test_expects(
        self, planner: TestClient, plan_id: str
    ) -> None:
        body = planner.get(f"/api/plans/{plan_id}/validation").json()
        assert body["error_count"] == 2
        assert body["warning_count"] == 11

    def test_findings_carry_a_key_and_params_not_a_sentence(
        self, planner: TestClient, plan_id: str
    ) -> None:
        finding = planner.get(f"/api/plans/{plan_id}/validation").json()["findings"][0]
        assert finding["message_key"]
        assert "message" not in finding
        assert all(isinstance(v, str) for v in finding["params"].values())

    def test_replacing_budgets_changes_the_next_response(
        self, planner: TestClient, plan_id: str
    ) -> None:
        """Carried from #25, where the endpoint did not exist yet."""
        profile_id = planner.get("/api/auth/me").json()["profile_id"]
        before = planner.get(f"/api/plans/{plan_id}/validation").json()["warning_count"]
        planner.put(
            f"/api/profiles/{profile_id}/slot-budgets",
            json=[{"slot": "dinner", "kcal_min": "0", "kcal_max": "99999", "protein_min": "0"}],
        )
        after = planner.get(f"/api/plans/{plan_id}/validation").json()["warning_count"]
        assert after != before

    def test_both_roles_may_read(self, follower: TestClient, plan_id: str) -> None:
        assert follower.get(f"/api/plans/{plan_id}/validation").status_code == 200


class TestShoppingList:
    def test_matches_the_golden_shopping_test(self, planner: TestClient, plan_id: str) -> None:
        lines = planner.get(f"/api/plans/{plan_id}/shopping-list").json()["lines"]
        by_id = {line["ingredient_id"]: line for line in lines}
        assert by_id["turkey_thigh"]["needed_raw_g"] == "553.8"
        assert by_id["spinach"]["needed_raw_g"] == "530"
        assert by_id["bell_pepper"]["packages"] == 7

    def test_lines_are_grouped_by_shop_section(self, planner: TestClient, plan_id: str) -> None:
        sections = [
            line["shop_section"]
            for line in planner.get(f"/api/plans/{plan_id}/shopping-list").json()["lines"]
        ]
        assert sections == sorted(sections)

    def test_quantities_are_strings_not_json_numbers(
        self, planner: TestClient, plan_id: str
    ) -> None:
        raw = json.loads(planner.get(f"/api/plans/{plan_id}/shopping-list").text)
        line = raw["lines"][0]
        for field in ("needed_raw_g", "purchase_amount", "overage_g"):
            assert isinstance(line[field], str)

    def test_the_flatbread_is_flagged_critical(self, planner: TestClient, plan_id: str) -> None:
        lines = planner.get(f"/api/plans/{plan_id}/shopping-list").json()["lines"]
        flatbread = next(line for line in lines if line["ingredient_id"] == "tortilla_wholegrain")
        assert flatbread["size_is_critical"] is True

    def test_staples_are_flagged(self, planner: TestClient, plan_id: str) -> None:
        lines = planner.get(f"/api/plans/{plan_id}/shopping-list").json()["lines"]
        assert (
            next(line for line in lines if line["ingredient_id"] == "olive_oil")["is_staple"]
            is True
        )

    def test_both_roles_may_read(self, follower: TestClient, plan_id: str) -> None:
        assert follower.get(f"/api/plans/{plan_id}/shopping-list").status_code == 200


class TestCheckOff:
    def test_checking_an_item_persists(self, planner: TestClient, plan_id: str) -> None:
        planner.patch(f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": True})
        lines = planner.get(f"/api/plans/{plan_id}/shopping-list").json()["lines"]
        assert next(x for x in lines if x["ingredient_id"] == "banana")["checked"] is True

    def test_the_follower_may_check_items_off(self, follower: TestClient, plan_id: str) -> None:
        """The follower is the one in the shop."""
        response = follower.patch(
            f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": True}
        )
        assert response.status_code == 200
        assert response.json()["checked"] is True

    def test_state_is_visible_to_the_other_role(
        self, planner: TestClient, follower: TestClient, plan_id: str
    ) -> None:
        follower.patch(f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": True})
        lines = planner.get(f"/api/plans/{plan_id}/shopping-list").json()["lines"]
        assert next(x for x in lines if x["ingredient_id"] == "banana")["checked"] is True

    def test_checking_twice_is_idempotent(self, planner: TestClient, plan_id: str) -> None:
        first = planner.patch(f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": True})
        second = planner.patch(f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": True})
        assert first.status_code == second.status_code == 200

    def test_unchecking_works(self, planner: TestClient, plan_id: str) -> None:
        planner.patch(f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": True})
        body = planner.patch(
            f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": False}
        ).json()
        assert body["checked"] is False

    def test_an_ingredient_not_in_this_list_is_404(self, planner: TestClient, plan_id: str) -> None:
        assert (
            planner.patch(
                f"/api/plans/{plan_id}/shopping-list/cocoa_nonexistent",
                json={"checked": True},
            ).status_code
            == 404
        )

    def test_state_is_scoped_to_the_plan(self, planner: TestClient, plan_id: str) -> None:
        """Last week's ticks must not carry into this week."""
        planner.patch(f"/api/plans/{plan_id}/shopping-list/banana", json={"checked": True})
        other = planner.post(
            "/api/plans",
            json={"name": "Другая", "start_date": "2026-11-09", "copy_from_plan_id": plan_id},
        ).json()["id"]
        lines = planner.get(f"/api/plans/{other}/shopping-list").json()["lines"]
        assert next(x for x in lines if x["ingredient_id"] == "banana")["checked"] is False


class TestPrepPlan:
    def test_returns_one_session_per_batch_module(self, planner: TestClient, plan_id: str) -> None:
        body = planner.get(f"/api/plans/{plan_id}/prep-plan").json()
        assert {s["module_id"] for s in body} == {"lunch_rice_noodles_turkey", "lunch_roll_chicken"}

    def test_each_session_carries_its_days_and_breakdown(
        self, planner: TestClient, plan_id: str
    ) -> None:
        body = planner.get(f"/api/plans/{plan_id}/prep-plan").json()
        session = next(s for s in body if s["module_id"] == "lunch_rice_noodles_turkey")
        assert session["day_indexes"] == [0, 1, 2]
        assert session["portions"] == 3
        turkey = next(i for i in session["items"] if i["ingredient_id"] == "turkey_thigh")
        assert turkey["grams_raw"] == "553.8"
        assert turkey["grams_cooked_per_portion"] == "120"

    def test_a_plan_with_no_batch_modules_returns_an_empty_list(self, planner: TestClient) -> None:
        empty = planner.post(
            "/api/plans", json={"name": "Пустая", "start_date": "2026-11-16"}
        ).json()["id"]
        response = planner.get(f"/api/plans/{empty}/prep-plan")
        assert response.status_code == 200
        assert response.json() == []

    def test_both_roles_may_read(self, follower: TestClient, plan_id: str) -> None:
        assert follower.get(f"/api/plans/{plan_id}/prep-plan").status_code == 200


class TestNoArithmeticInHandlers:
    def test_the_router_computes_nothing(self) -> None:
        import pathlib
        import re

        source = pathlib.Path("src/ration/api/routers/derived.py").read_text(encoding="utf-8")
        assert not re.search(r"Decimal\(|sum\(|/ \w+\.yield_factor", source)


class TestOwnership:
    def test_another_profiles_plan_is_404(self, planner: TestClient) -> None:
        for path in ("validation", "shopping-list", "prep-plan"):
            assert planner.get(f"/api/plans/not-mine/{path}").status_code == 404
