"""Profile, budget and rule endpoints."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def profile_id(planner: TestClient) -> str:
    return planner.get("/api/auth/me").json()["profile_id"]


class TestRead:
    def test_returns_targets_budgets_and_both_rule_kinds(
        self, planner: TestClient, profile_id: str
    ) -> None:
        body = planner.get(f"/api/profiles/{profile_id}").json()
        assert body["daily_kcal_target"] == "1700"
        assert len(body["slot_budgets"]) == 5
        assert body["frequency_rules"]

    def test_a_follower_may_read(self, follower: TestClient, profile_id: str) -> None:
        assert follower.get(f"/api/profiles/{profile_id}").status_code == 200

    def test_another_profile_is_404_even_for_the_planner(self, planner: TestClient) -> None:
        assert planner.get("/api/profiles/someone-else").status_code == 404


class TestTargets:
    def test_patches_only_what_is_sent(self, planner: TestClient, profile_id: str) -> None:
        before = planner.get(f"/api/profiles/{profile_id}").json()
        after = planner.patch(
            f"/api/profiles/{profile_id}", json={"daily_kcal_target": "1800"}
        ).json()
        assert after["daily_kcal_target"] == "1800"
        assert after["daily_protein_min"] == before["daily_protein_min"]

    def test_a_negative_tolerance_is_422(self, planner: TestClient, profile_id: str) -> None:
        response = planner.patch(
            f"/api/profiles/{profile_id}", json={"daily_kcal_tolerance": "-10"}
        )
        assert response.status_code == 422

    def test_a_non_positive_target_is_422(self, planner: TestClient, profile_id: str) -> None:
        assert (
            planner.patch(
                f"/api/profiles/{profile_id}", json={"daily_kcal_target": "0"}
            ).status_code
            == 422
        )

    def test_a_follower_gets_403(self, follower: TestClient, profile_id: str) -> None:
        assert (
            follower.patch(
                f"/api/profiles/{profile_id}", json={"daily_kcal_target": "1000"}
            ).status_code
            == 403
        )


class TestSlotBudgets:
    BUDGETS: ClassVar[list[dict[str, Any]]] = [
        {"slot": "breakfast", "kcal_min": "400", "kcal_max": "450", "protein_min": "30"},
        {
            "slot": "dinner",
            "kcal_min": "450",
            "kcal_max": "500",
            "protein_min": "35",
            "protein_max": "45",
        },
        {"slot": "treat", "kcal_min": "0", "kcal_max": "150", "protein_min": "0", "optional": True},
    ]

    def test_replaces_wholesale(self, planner: TestClient, profile_id: str) -> None:
        """Anything omitted is deleted — a partial update cannot express a removal."""
        body = planner.put(f"/api/profiles/{profile_id}/slot-budgets", json=self.BUDGETS).json()
        assert {b["slot"] for b in body} == {"breakfast", "dinner", "treat"}

    def test_a_null_protein_ceiling_round_trips(self, planner: TestClient, profile_id: str) -> None:
        """Protein is a floor, not a band (docs/decisions.md D2)."""
        body = planner.put(f"/api/profiles/{profile_id}/slot-budgets", json=self.BUDGETS).json()
        breakfast = next(b for b in body if b["slot"] == "breakfast")
        assert breakfast["protein_max"] is None

    def test_optional_round_trips(self, planner: TestClient, profile_id: str) -> None:
        body = planner.put(f"/api/profiles/{profile_id}/slot-budgets", json=self.BUDGETS).json()
        assert next(b for b in body if b["slot"] == "treat")["optional"] is True

    def test_a_duplicate_slot_is_422(self, planner: TestClient, profile_id: str) -> None:
        duplicated = [*self.BUDGETS, self.BUDGETS[0]]
        assert (
            planner.put(f"/api/profiles/{profile_id}/slot-budgets", json=duplicated).status_code
            == 422
        )

    def test_an_inverted_range_is_422(self, planner: TestClient, profile_id: str) -> None:
        bad = [dict(self.BUDGETS[0], kcal_min="500", kcal_max="400")]
        assert planner.put(f"/api/profiles/{profile_id}/slot-budgets", json=bad).status_code == 422

    def test_replacing_twice_in_a_row_works(self, planner: TestClient, profile_id: str) -> None:
        planner.put(f"/api/profiles/{profile_id}/slot-budgets", json=self.BUDGETS)
        second = planner.put(f"/api/profiles/{profile_id}/slot-budgets", json=self.BUDGETS[:1])
        assert second.status_code == 200
        assert len(second.json()) == 1

    def test_a_follower_gets_403(self, follower: TestClient, profile_id: str) -> None:
        assert (
            follower.put(f"/api/profiles/{profile_id}/slot-budgets", json=self.BUDGETS).status_code
            == 403
        )


class TestIngredientRules:
    def test_replaces_wholesale(self, planner: TestClient, profile_id: str) -> None:
        body = planner.put(
            f"/api/profiles/{profile_id}/ingredient-rules",
            json=[{"ingredient_id": "banana", "rule": "excluded"}],
        ).json()
        assert body == [{"ingredient_id": "banana", "rule": "excluded", "threshold_g": None}]

    def test_a_caution_without_a_threshold_is_422(
        self, planner: TestClient, profile_id: str
    ) -> None:
        response = planner.put(
            f"/api/profiles/{profile_id}/ingredient-rules",
            json=[{"ingredient_id": "banana", "rule": "caution"}],
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "threshold_g"

    def test_a_caution_with_a_threshold_is_accepted(
        self, planner: TestClient, profile_id: str
    ) -> None:
        body = planner.put(
            f"/api/profiles/{profile_id}/ingredient-rules",
            json=[{"ingredient_id": "banana", "rule": "caution", "threshold_g": "60"}],
        ).json()
        assert body[0]["threshold_g"] == "60"

    def test_an_unknown_ingredient_is_422_not_500(
        self, planner: TestClient, profile_id: str
    ) -> None:
        response = planner.put(
            f"/api/profiles/{profile_id}/ingredient-rules",
            json=[{"ingredient_id": "ghost", "rule": "excluded"}],
        )
        assert response.status_code == 422
        assert "ghost" in response.json()["error"]["message"]

    def test_a_duplicate_rule_is_422(self, planner: TestClient, profile_id: str) -> None:
        assert (
            planner.put(
                f"/api/profiles/{profile_id}/ingredient-rules",
                json=[
                    {"ingredient_id": "banana", "rule": "excluded"},
                    {"ingredient_id": "banana", "rule": "excluded"},
                ],
            ).status_code
            == 422
        )

    def test_rules_use_slugs_not_row_ids(self, planner: TestClient, profile_id: str) -> None:
        planner.put(
            f"/api/profiles/{profile_id}/ingredient-rules",
            json=[{"ingredient_id": "banana", "rule": "excluded"}],
        )
        body = planner.get(f"/api/profiles/{profile_id}").json()
        assert body["ingredient_rules"][0]["ingredient_id"] == "banana"


class TestFrequencyRules:
    RULES: ClassVar[list[dict[str, Any]]] = [
        {"tag": "liver", "max_per_week": 1},
        {"tag": "alcohol", "max_per_week": 1, "blocked_on_templates": ["training", "duty_24h"]},
        {"tag": "fish", "max_per_week": None},
    ]

    def test_replaces_wholesale(self, planner: TestClient, profile_id: str) -> None:
        body = planner.put(f"/api/profiles/{profile_id}/frequency-rules", json=self.RULES).json()
        assert {r["tag"] for r in body} == {"liver", "alcohol", "fish"}

    def test_blocked_templates_round_trip_through_the_comma_column(
        self, planner: TestClient, profile_id: str
    ) -> None:
        planner.put(f"/api/profiles/{profile_id}/frequency-rules", json=self.RULES)
        body = planner.get(f"/api/profiles/{profile_id}").json()
        alcohol = next(r for r in body["frequency_rules"] if r["tag"] == "alcohol")
        assert set(alcohol["blocked_on_templates"]) == {"training", "duty_24h"}

    def test_a_null_limit_means_no_count_limit(self, planner: TestClient, profile_id: str) -> None:
        body = planner.put(f"/api/profiles/{profile_id}/frequency-rules", json=self.RULES).json()
        assert next(r for r in body if r["tag"] == "fish")["max_per_week"] is None

    def test_a_duplicate_tag_is_422(self, planner: TestClient, profile_id: str) -> None:
        assert (
            planner.put(
                f"/api/profiles/{profile_id}/frequency-rules",
                json=[{"tag": "liver", "max_per_week": 1}, {"tag": "liver", "max_per_week": 2}],
            ).status_code
            == 422
        )

    def test_a_negative_limit_is_422(self, planner: TestClient, profile_id: str) -> None:
        assert (
            planner.put(
                f"/api/profiles/{profile_id}/frequency-rules",
                json=[{"tag": "liver", "max_per_week": -1}],
            ).status_code
            == 422
        )

    def test_an_unknown_template_is_422(self, planner: TestClient, profile_id: str) -> None:
        assert (
            planner.put(
                f"/api/profiles/{profile_id}/frequency-rules",
                json=[{"tag": "x", "blocked_on_templates": ["nonsense"]}],
            ).status_code
            == 422
        )

    def test_a_follower_gets_403(self, follower: TestClient, profile_id: str) -> None:
        assert (
            follower.put(f"/api/profiles/{profile_id}/frequency-rules", json=self.RULES).status_code
            == 403
        )


class TestNoFiveHundreds:
    @pytest.mark.parametrize(
        "path",
        [
            "/slot-budgets",
            "/ingredient-rules",
            "/frequency-rules",
        ],
    )
    def test_a_malformed_body_never_500s(
        self, planner: TestClient, profile_id: str, path: str
    ) -> None:
        for payload in ([], [{}], [{"nonsense": 1}], "not-a-list"):
            response = planner.put(f"/api/profiles/{profile_id}{path}", json=payload)
            assert response.status_code < 500, f"{path} {payload!r} -> {response.status_code}"
