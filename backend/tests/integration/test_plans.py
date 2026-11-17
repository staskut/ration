"""Plan, day and entry endpoints (#26, #27)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

NEW_PLAN = {"name": "Неделя 2", "start_date": "2026-10-19"}


@pytest.fixture
def plan_id(planner: TestClient) -> str:
    return planner.post("/api/plans", json=NEW_PLAN).json()["id"]


@pytest.fixture
def seeded_plan_id(planner: TestClient) -> str:
    plans = planner.get("/api/plans").json()
    return next(p["id"] for p in plans if p["name"] == "Pilot week 1")


class TestCreate:
    def test_a_new_plan_always_has_exactly_seven_days(self, planner: TestClient) -> None:
        body = planner.post("/api/plans", json=NEW_PLAN).json()
        assert len(body["days"]) == 7
        assert [d["day_index"] for d in body["days"]] == list(range(7))

    def test_days_are_dated_consecutively_from_the_start(self, planner: TestClient) -> None:
        body = planner.post("/api/plans", json=NEW_PLAN).json()
        assert [d["date"] for d in body["days"]][:3] == ["2026-10-19", "2026-10-20", "2026-10-21"]

    def test_a_new_plan_is_a_draft(self, planner: TestClient) -> None:
        assert planner.post("/api/plans", json=NEW_PLAN).json()["status"] == "draft"

    def test_a_follower_gets_403(self, follower: TestClient) -> None:
        assert follower.post("/api/plans", json=NEW_PLAN).status_code == 403


class TestCopy:
    def test_copying_reproduces_the_source_entries(
        self, planner: TestClient, seeded_plan_id: str
    ) -> None:
        copy = planner.post(
            "/api/plans", json=dict(NEW_PLAN, copy_from_plan_id=seeded_plan_id)
        ).json()
        source = planner.get(f"/api/plans/{seeded_plan_id}").json()
        assert [len(d["entries"]) for d in copy["days"]] == [
            len(d["entries"]) for d in source["days"]
        ]

    def test_copying_reproduces_the_day_templates(
        self, planner: TestClient, seeded_plan_id: str
    ) -> None:
        copy = planner.post(
            "/api/plans", json=dict(NEW_PLAN, copy_from_plan_id=seeded_plan_id)
        ).json()
        assert [d["day_template"] for d in copy["days"]] == [
            "training",
            "normal",
            "long_shift",
            "training",
            "normal",
            "normal",
            "normal",
        ]

    def test_the_copy_is_independent_of_the_source(
        self, planner: TestClient, seeded_plan_id: str
    ) -> None:
        copy = planner.post(
            "/api/plans", json=dict(NEW_PLAN, copy_from_plan_id=seeded_plan_id)
        ).json()
        entry = copy["days"][0]["entries"][0]
        planner.delete(f"/api/plans/{copy['id']}/entries/{entry['id']}")
        source = planner.get(f"/api/plans/{seeded_plan_id}").json()
        assert len(source["days"][0]["entries"]) == 4

    def test_copying_a_plan_from_another_profile_is_404(self, planner: TestClient) -> None:
        assert (
            planner.post(
                "/api/plans", json=dict(NEW_PLAN, copy_from_plan_id="someone-elses")
            ).status_code
            == 404
        )


class TestReadAndUpdate:
    def test_lists_plans_most_recent_first(self, planner: TestClient) -> None:
        planner.post("/api/plans", json=NEW_PLAN)
        dates = [p["start_date"] for p in planner.get("/api/plans").json()]
        assert dates == sorted(dates, reverse=True)

    def test_get_returns_days_entries_and_totals(
        self, planner: TestClient, seeded_plan_id: str
    ) -> None:
        body = planner.get(f"/api/plans/{seeded_plan_id}").json()
        day = body["days"][0]
        # Matches the domain engine exactly, from YAML or from the database:
        # the NUMERIC(12,4) round trip is lossless for these values.
        assert day["kcal"] == "1577.59"
        assert day["slot_totals"]
        assert day["entries"][0]["module_name"]

    def test_patch_changes_name_and_status(self, planner: TestClient, plan_id: str) -> None:
        body = planner.patch(
            f"/api/plans/{plan_id}", json={"name": "Переименовано", "status": "active"}
        ).json()
        assert body["name"] == "Переименовано"
        assert body["status"] == "active"

    def test_another_profiles_plan_is_404(self, planner: TestClient) -> None:
        assert planner.get("/api/plans/not-mine").status_code == 404

    def test_a_follower_may_read_but_not_mutate(
        self, follower: TestClient, seeded_plan_id: str
    ) -> None:
        assert follower.get(f"/api/plans/{seeded_plan_id}").status_code == 200
        assert follower.patch(f"/api/plans/{seeded_plan_id}", json={"name": "x"}).status_code == 403
        assert follower.delete(f"/api/plans/{seeded_plan_id}").status_code == 403


class TestDelete:
    def test_deleting_cascades_to_days_and_entries(
        self, planner: TestClient, seeded_plan_id: str
    ) -> None:
        assert planner.delete(f"/api/plans/{seeded_plan_id}").status_code == 204
        assert planner.get(f"/api/plans/{seeded_plan_id}").status_code == 404


class TestDays:
    def test_setting_a_template_returns_fresh_validation(
        self, planner: TestClient, plan_id: str
    ) -> None:
        body = planner.put(f"/api/plans/{plan_id}/days/0", json={"day_template": "training"}).json()
        assert body["day"]["day_template"] == "training"
        assert "findings" in body["validation"]

    def test_notes_round_trip(self, planner: TestClient, plan_id: str) -> None:
        body = planner.put(f"/api/plans/{plan_id}/days/3", json={"notes": "дежурство"}).json()
        assert body["day"]["notes"] == "дежурство"

    @pytest.mark.parametrize("bad", [-1, 7, 99])
    def test_a_day_index_outside_the_week_is_422(
        self, planner: TestClient, plan_id: str, bad: int
    ) -> None:
        assert (
            planner.put(f"/api/plans/{plan_id}/days/{bad}", json={"notes": "x"}).status_code == 422
        )

    def test_making_a_day_a_training_day_surfaces_the_wine_gate(
        self, planner: TestClient, seeded_plan_id: str
    ) -> None:
        """Day 1 carries the wine treat; marking it a training day must fire
        TEMPLATE_GATE_VIOLATED immediately."""
        body = planner.put(
            f"/api/plans/{seeded_plan_id}/days/1", json={"day_template": "training"}
        ).json()
        codes = [f["code"] for f in body["validation"]["findings"]]
        assert "TEMPLATE_GATE_VIOLATED" in codes


class TestEntries:
    def test_adding_an_entry_returns_it_with_fresh_validation(
        self, planner: TestClient, plan_id: str
    ) -> None:
        body = planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "dinner", "module_id": "dinner_shrimp_asian"},
        ).json()
        assert body["entry"]["module_id"] == "dinner_shrimp_asian"
        assert body["entry"]["kcal"]
        assert "error_count" in body["validation"]

    def test_a_second_main_in_a_slot_is_409(self, planner: TestClient, plan_id: str) -> None:
        planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "dinner", "module_id": "dinner_shrimp_asian"},
        )
        response = planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "dinner", "module_id": "dinner_squid_pepper"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SLOT_ALREADY_HAS_A_MAIN"

    def test_several_sides_in_one_slot_are_accepted(
        self, planner: TestClient, plan_id: str
    ) -> None:
        planner.post(
            "/api/modules",
            json={
                "name": "Гарнир А",
                "slot": "dinner",
                "role": "side",
                "lines": [{"ingredient_id": "carrot", "grams_cooked": "100"}],
            },
        )
        planner.post(
            "/api/modules",
            json={
                "name": "Гарнир Б",
                "slot": "dinner",
                "role": "side",
                "lines": [{"ingredient_id": "spinach", "grams_cooked": "50"}],
            },
        )
        planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "dinner", "module_id": "dinner_shrimp_asian"},
        )
        a = planner.post(
            f"/api/plans/{plan_id}/days/0/entries", json={"slot": "dinner", "module_id": "garnir_a"}
        )
        b = planner.post(
            f"/api/plans/{plan_id}/days/0/entries", json={"slot": "dinner", "module_id": "garnir_b"}
        )
        assert a.status_code == 201 and b.status_code == 201

    @pytest.mark.parametrize("bad", ["0.4", "1.6", "0", "3"])
    def test_a_portion_factor_outside_the_range_is_422(
        self, planner: TestClient, plan_id: str, bad: str
    ) -> None:
        response = planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "dinner", "module_id": "dinner_shrimp_asian", "portion_factor": bad},
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "portion_factor"

    def test_a_module_for_another_slot_is_422(self, planner: TestClient, plan_id: str) -> None:
        response = planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "breakfast", "module_id": "dinner_shrimp_asian"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MODULE_SLOT_MISMATCH"

    def test_an_unknown_module_is_422_not_500(self, planner: TestClient, plan_id: str) -> None:
        assert (
            planner.post(
                f"/api/plans/{plan_id}/days/0/entries",
                json={"slot": "dinner", "module_id": "ghost"},
            ).status_code
            == 422
        )

    def test_position_defaults_to_the_next_free_slot_position(
        self, planner: TestClient, plan_id: str
    ) -> None:
        planner.post(
            "/api/modules",
            json={
                "name": "Гарнир В",
                "slot": "dinner",
                "role": "side",
                "lines": [{"ingredient_id": "carrot", "grams_cooked": "100"}],
            },
        )
        first = planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "dinner", "module_id": "dinner_shrimp_asian"},
        )
        second = planner.post(
            f"/api/plans/{plan_id}/days/0/entries", json={"slot": "dinner", "module_id": "garnir_v"}
        )
        assert first.json()["entry"]["position"] == 0
        assert second.json()["entry"]["position"] == 1

    def test_patching_an_entry_returns_fresh_validation(
        self, planner: TestClient, plan_id: str
    ) -> None:
        created = planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "dinner", "module_id": "dinner_shrimp_asian"},
        ).json()["entry"]
        body = planner.patch(
            f"/api/plans/{plan_id}/entries/{created['id']}",
            json={"portion_factor": "0.5"},
        ).json()
        assert body["entry"]["portion_factor"] == "0.5"
        assert "findings" in body["validation"]

    def test_deleting_an_entry_returns_the_report(self, planner: TestClient, plan_id: str) -> None:
        created = planner.post(
            f"/api/plans/{plan_id}/days/0/entries",
            json={"slot": "dinner", "module_id": "dinner_shrimp_asian"},
        ).json()["entry"]
        body = planner.delete(f"/api/plans/{plan_id}/entries/{created['id']}").json()
        assert "findings" in body and "error_count" in body

    def test_an_entry_from_another_plan_is_404(self, planner: TestClient, plan_id: str) -> None:
        assert (
            planner.patch(
                f"/api/plans/{plan_id}/entries/not-an-entry", json={"position": 1}
            ).status_code
            == 404
        )

    def test_validation_reflects_the_change_immediately(
        self, planner: TestClient, seeded_plan_id: str
    ) -> None:
        """A fourth treat must fire FREQUENCY_EXCEEDED in the same response."""
        body = planner.post(
            f"/api/plans/{seeded_plan_id}/days/0/entries",
            json={"slot": "treat", "module_id": "treat_ice_cream"},
        ).json()
        codes = [f["code"] for f in body["validation"]["findings"]]
        assert "FREQUENCY_EXCEEDED" in codes

    def test_a_follower_gets_403_on_entry_mutations(
        self, follower: TestClient, seeded_plan_id: str
    ) -> None:
        assert (
            follower.post(
                f"/api/plans/{seeded_plan_id}/days/0/entries",
                json={"slot": "treat", "module_id": "treat_wine"},
            ).status_code
            == 403
        )


class TestNoFiveHundreds:
    def test_malformed_bodies_never_500(self, planner: TestClient, plan_id: str) -> None:
        for payload in ({}, {"slot": "nonsense"}, {"module_id": None}, {"slot": "dinner"}):
            response = planner.post(f"/api/plans/{plan_id}/days/0/entries", json=payload)
            assert response.status_code < 500, f"{payload!r} -> {response.status_code}"
