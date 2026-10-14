"""Module endpoints: filters, computed totals, line handling, role boundary."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

NEW = {
    "name": "Тестовый модуль",
    "slot": "dinner",
    "role": "main",
    "batch_portions": 1,
    "lines": [
        {"ingredient_id": "white_fish", "grams_cooked": "170"},
        {"ingredient_id": "pumpkin", "grams_cooked": "180", "size_is_critical": True},
    ],
    "tags": ["fish", "home_only"],
}


class TestListAndFilter:
    def test_lists_the_library(self, planner: TestClient) -> None:
        assert len(planner.get("/api/modules").json()) == 19

    def test_filters_by_slot(self, planner: TestClient) -> None:
        body = planner.get("/api/modules", params={"slot": "dinner"}).json()
        assert body and {m["slot"] for m in body} == {"dinner"}

    def test_filters_by_role(self, planner: TestClient) -> None:
        body = planner.get("/api/modules", params={"role": "main"}).json()
        assert body and {m["role"] for m in body} == {"main"}

    def test_filters_by_tag(self, planner: TestClient) -> None:
        body = planner.get("/api/modules", params={"tag": "salted_fish"}).json()
        assert {m["id"] for m in body} == {
            "dinner_salted_salmon_eggs",
            "dinner_herring_cottage",
        }

    def test_filters_combine(self, planner: TestClient) -> None:
        body = planner.get("/api/modules", params={"slot": "lunch", "tag": "batch"}).json()
        assert len(body) == 2


class TestComputedTotals:
    def test_totals_come_from_the_domain_engine(self, planner: TestClient) -> None:
        body = planner.get("/api/modules/dinner_fish_pumpkin_carrot").json()
        # kcal: fish 170x1.05 + pumpkin 180x0.34 + carrot 100x0.41
        #       + yogurt 50x0.60 + olive oil 12x8.84
        # protein: 39.1 + 1.98 + 0.9 + 2.25 + 0
        assert body["kcal"] == "416.78"
        assert body["protein_g"] == "44.23"

    def test_totals_are_strings_not_json_numbers(self, planner: TestClient) -> None:
        raw = json.loads(planner.get("/api/modules/snack_banana_nuts").text)
        assert isinstance(raw["kcal"], str)
        assert isinstance(raw["protein_g"], str)

    def test_correcting_an_ingredient_changes_every_module_using_it(
        self, planner: TestClient
    ) -> None:
        """The reason totals are computed and never stored."""
        before = planner.get("/api/modules/lunch_rice_noodles_turkey").json()["kcal"]
        planner.patch("/api/ingredients/turkey_thigh", json={"kcal_per_100g": "285"})
        after = planner.get("/api/modules/lunch_rice_noodles_turkey").json()["kcal"]
        # 120 g of turkey, +100 kcal per 100 g.
        assert float(after) - float(before) == pytest.approx(120.0)

    def test_submitted_totals_are_never_persisted(self, planner: TestClient) -> None:
        body = dict(NEW, kcal="99999", protein_g="99999")
        created = planner.post("/api/modules", json=body).json()
        assert created["kcal"] != "99999"
        assert planner.get(f"/api/modules/{created['id']}").json()["kcal"] != "99999"


class TestLines:
    def test_line_order_is_preserved_on_round_trip(self, planner: TestClient) -> None:
        created = planner.post("/api/modules", json=NEW).json()
        fetched = planner.get(f"/api/modules/{created['id']}").json()
        assert [line["ingredient_id"] for line in fetched["lines"]] == [
            "white_fish",
            "pumpkin",
        ]

    def test_reordering_lines_sticks(self, planner: TestClient) -> None:
        created = planner.post("/api/modules", json=NEW).json()
        reversed_lines = list(reversed(NEW["lines"]))
        updated = planner.patch(
            f"/api/modules/{created['id']}", json={"lines": reversed_lines}
        ).json()
        assert [line["ingredient_id"] for line in updated["lines"]] == [
            "pumpkin",
            "white_fish",
        ]

    def test_size_is_critical_survives_create_and_update(self, planner: TestClient) -> None:
        created = planner.post("/api/modules", json=NEW).json()
        assert [line["size_is_critical"] for line in created["lines"]] == [False, True]
        updated = planner.patch(
            f"/api/modules/{created['id']}",
            json={
                "lines": [
                    {"ingredient_id": "white_fish", "grams_cooked": "100", "size_is_critical": True}
                ]
            },
        ).json()
        assert updated["lines"][0]["size_is_critical"] is True

    def test_a_yield_override_survives(self, planner: TestClient) -> None:
        body = dict(
            NEW,
            name="С переопределением",
            lines=[
                {
                    "ingredient_id": "bell_pepper",
                    "grams_cooked": "100",
                    "yield_factor_override": "0.65",
                }
            ],
        )
        created = planner.post("/api/modules", json=body).json()
        assert created["lines"][0]["yield_factor_override"] == "0.65"

    def test_replacing_lines_twice_in_a_row_works(self, planner: TestClient) -> None:
        """The orphan-delete ordering trap that broke re-seeding in #21."""
        created = planner.post("/api/modules", json=NEW).json()
        first = planner.patch(
            f"/api/modules/{created['id']}",
            json={"lines": [{"ingredient_id": "banana", "grams_cooked": "100"}]},
        )
        second = planner.patch(
            f"/api/modules/{created['id']}",
            json={
                "lines": [
                    {"ingredient_id": "nuts", "grams_cooked": "20"},
                    {"ingredient_id": "banana", "grams_cooked": "50"},
                ]
            },
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert len(second.json()["lines"]) == 2

    def test_replacing_tags_twice_in_a_row_works(self, planner: TestClient) -> None:
        created = planner.post("/api/modules", json=NEW).json()
        planner.patch(f"/api/modules/{created['id']}", json={"tags": ["a", "b"]})
        response = planner.patch(f"/api/modules/{created['id']}", json={"tags": ["c"]})
        assert response.status_code == 200
        assert response.json()["tags"] == ["c"]


class TestValidation:
    def test_a_module_with_no_lines_is_422(self, planner: TestClient) -> None:
        response = planner.post("/api/modules", json=dict(NEW, lines=[]))
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "lines"

    @pytest.mark.parametrize("bad", [0, 8, -1, 99])
    def test_batch_portions_outside_the_week_is_422(self, planner: TestClient, bad: int) -> None:
        response = planner.post("/api/modules", json=dict(NEW, batch_portions=bad))
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "batch_portions"

    def test_the_boundary_values_are_accepted(self, planner: TestClient) -> None:
        for portions in (1, 7):
            response = planner.post(
                "/api/modules", json=dict(NEW, name=f"Партия {portions}", batch_portions=portions)
            )
            assert response.status_code == 201

    def test_an_unknown_ingredient_is_422_not_500(self, planner: TestClient) -> None:
        body = dict(NEW, lines=[{"ingredient_id": "ghost", "grams_cooked": "10"}])
        response = planner.post("/api/modules", json=body)
        assert response.status_code == 422
        assert "ghost" in response.json()["error"]["message"]

    def test_a_non_positive_gram_amount_is_422(self, planner: TestClient) -> None:
        body = dict(NEW, lines=[{"ingredient_id": "banana", "grams_cooked": "0"}])
        assert planner.post("/api/modules", json=body).status_code == 422

    def test_a_duplicate_name_is_409(self, planner: TestClient) -> None:
        planner.post("/api/modules", json=NEW)
        assert planner.post("/api/modules", json=NEW).status_code == 409


class TestDelete:
    def test_an_unused_module_can_be_deleted(self, planner: TestClient) -> None:
        created = planner.post("/api/modules", json=NEW).json()
        assert planner.delete(f"/api/modules/{created['id']}").status_code == 204
        assert planner.get(f"/api/modules/{created['id']}").status_code == 404

    def test_one_a_plan_still_uses_is_409_not_500(self, planner: TestClient) -> None:
        response = planner.delete("/api/modules/lunch_rice_noodles_turkey")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "MODULE_IN_USE"

    def test_an_unknown_module_is_404(self, planner: TestClient) -> None:
        assert planner.delete("/api/modules/ghost").status_code == 404


class TestRoleBoundary:
    def test_a_follower_may_read(self, follower: TestClient) -> None:
        assert follower.get("/api/modules").status_code == 200
        assert follower.get("/api/modules/snack_banana_nuts").status_code == 200

    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        [
            ("post", "/api/modules", NEW),
            ("patch", "/api/modules/snack_banana_nuts", {"name": "x"}),
            ("delete", "/api/modules/snack_banana_nuts", None),
        ],
    )
    def test_a_follower_gets_403_on_mutations(
        self, follower: TestClient, method: str, path: str, payload: dict | None
    ) -> None:
        call = getattr(follower, method)
        response = call(path, json=payload) if payload is not None else call(path)
        assert response.status_code == 403

    def test_unauthenticated_is_401(self, api: TestClient) -> None:
        assert api.get("/api/modules").status_code == 401
