"""Ingredient endpoints: search, CRUD, role boundary, and decimal fidelity."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

NEW = {
    "names": {"ru": "Треска"},
    "aliases": ["белая рыба", "cod"],
    "kcal_per_100g": "82",
    "protein_per_100g": "17.8",
    "yield_factor": "0.78",
    "yield_source": "estimated",
    "shop_section": "meat_fish",
}


class TestListAndSearch:
    def test_lists_the_whole_catalog(self, planner: TestClient) -> None:
        body = planner.get("/api/ingredients").json()
        assert len(body) == 40

    def test_filters_by_section(self, planner: TestClient) -> None:
        body = planner.get("/api/ingredients", params={"section": "meat_fish"}).json()
        assert body
        assert {i["shop_section"] for i in body} == {"meat_fish"}

    def test_searches_names_case_insensitively(self, planner: TestClient) -> None:
        body = planner.get("/api/ingredients", params={"q": "БАНАН"}).json()
        assert [i["id"] for i in body] == ["banana"]

    def test_searches_by_alias(self, planner: TestClient) -> None:
        """The point of aliases: "треска" must find the fish filed as "белая рыба"."""
        planner.post("/api/ingredients", json=NEW)
        by_alias = planner.get("/api/ingredients", params={"q": "cod"}).json()
        assert [i["id"] for i in by_alias] == ["treska"]

    def test_an_unmatched_search_is_empty_not_an_error(self, planner: TestClient) -> None:
        assert planner.get("/api/ingredients", params={"q": "zzzz"}).json() == []

    def test_results_are_sorted_in_the_callers_language(self, planner: TestClient) -> None:
        """Not in Russian regardless of who is asking, which is what it used to do.

        The seeded profile is `en`, so an English reader gets Avocado, Bananas,
        Pineapple. Sorting that by Russian name would have produced Ананас,
        Авокадо, Бананы — an order with no relation to the words on screen.
        """
        names = [i["names"]["en"] for i in planner.get("/api/ingredients").json()]
        assert names == sorted(names)

    def test_an_explicit_locale_overrides_the_callers(self, planner: TestClient) -> None:
        rows = planner.get("/api/ingredients", params={"locale": "ru"}).json()
        names = [i["names"]["ru"] for i in rows]
        assert names == sorted(names)


class TestDecimalsAreStrings:
    def test_every_numeric_field_comes_back_as_a_string(self, planner: TestClient) -> None:
        """A JSON number is a float and would reintroduce rounding drift."""
        raw = json.loads(planner.get("/api/ingredients/turkey_thigh").text)
        for field in ("kcal_per_100g", "protein_per_100g", "yield_factor"):
            assert isinstance(raw[field], str), f"{field} came back as {type(raw[field])}"

    def test_a_submitted_json_number_is_rejected(self, planner: TestClient) -> None:
        body = dict(NEW, names={"ru": "Пикша"}, kcal_per_100g=82.5)
        response = planner.post("/api/ingredients", json=body)
        assert response.status_code == 422

    def test_round_trip_preserves_the_value_exactly(self, planner: TestClient) -> None:
        created = planner.post("/api/ingredients", json=NEW).json()
        fetched = planner.get(f"/api/ingredients/{created['id']}").json()
        assert fetched["yield_factor"] == "0.78"
        assert fetched["protein_per_100g"] == "17.8"
        assert created == fetched


class TestCreate:
    def test_creates_and_returns_201(self, planner: TestClient) -> None:
        response = planner.post("/api/ingredients", json=NEW)
        assert response.status_code == 201
        assert response.json()["id"] == "treska"

    def test_the_slug_is_transliterated_from_the_russian_name(self, planner: TestClient) -> None:
        body = planner.post("/api/ingredients", json=dict(NEW, names={"ru": "Щука"})).json()
        assert body["id"] == "schuka"

    def test_a_duplicate_name_is_a_conflict(self, planner: TestClient) -> None:
        planner.post("/api/ingredients", json=NEW)
        assert planner.post("/api/ingredients", json=NEW).status_code == 409

    def test_a_missing_russian_name_is_422(self, planner: TestClient) -> None:
        response = planner.post("/api/ingredients", json=dict(NEW, names={"en": "Cod"}))
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "names.ru"


class TestYieldValidation:
    @pytest.mark.parametrize("bad", ["0", "-0.5", "5.5", "100"])
    def test_a_factor_outside_the_range_is_422_naming_the_field(
        self, planner: TestClient, bad: str
    ) -> None:
        response = planner.post(
            "/api/ingredients", json=dict(NEW, names={"ru": "Проба"}, yield_factor=bad)
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "yield_factor"

    def test_the_boundary_value_is_accepted(self, planner: TestClient) -> None:
        response = planner.post(
            "/api/ingredients",
            json=dict(NEW, names={"ru": "Лапша"}, yield_factor="5", yield_source="estimated"),
        )
        assert response.status_code == 201

    def test_a_unit_factor_cannot_claim_to_be_estimated(self, planner: TestClient) -> None:
        """Marking 1.0 as estimated would put it in the calibration backlog for
        no reason (docs/decisions.md D9)."""
        response = planner.post(
            "/api/ingredients",
            json=dict(NEW, names={"ru": "Соль"}, yield_factor="1", yield_source="estimated"),
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "yield_source"


class TestUpdate:
    def test_patches_only_what_is_sent(self, planner: TestClient) -> None:
        before = planner.get("/api/ingredients/banana").json()
        after = planner.patch("/api/ingredients/banana", json={"kcal_per_100g": "95"}).json()
        assert after["kcal_per_100g"] == "95"
        assert after["protein_per_100g"] == before["protein_per_100g"]

    def test_renaming_does_not_change_the_id(self, planner: TestClient) -> None:
        """A changed slug would orphan every module line referencing it."""
        after = planner.patch(
            "/api/ingredients/banana", json={"names": {"ru": "Банан спелый"}}
        ).json()
        assert after["id"] == "banana"
        assert after["names"]["ru"] == "Банан спелый"

    def test_aliases_can_be_replaced_twice_in_a_row(self, planner: TestClient) -> None:
        """The orphan-delete ordering that broke re-seeding in #21."""
        planner.patch("/api/ingredients/banana", json={"aliases": ["a", "b"]})
        response = planner.patch("/api/ingredients/banana", json={"aliases": ["c"]})
        assert response.status_code == 200
        assert response.json()["aliases"] == ["c"]

    def test_an_invalid_yield_is_rejected_on_patch_too(self, planner: TestClient) -> None:
        response = planner.patch("/api/ingredients/banana", json={"yield_factor": "9"})
        assert response.status_code == 422


class TestDelete:
    def test_an_unused_ingredient_can_be_deleted(self, planner: TestClient) -> None:
        created = planner.post("/api/ingredients", json=NEW).json()
        assert planner.delete(f"/api/ingredients/{created['id']}").status_code == 204
        assert planner.get(f"/api/ingredients/{created['id']}").status_code == 404

    def test_one_a_module_still_uses_is_409_not_500(self, planner: TestClient) -> None:
        """Checked before deleting; the foreign key would otherwise raise on
        commit and surface as a 500 with no useful message."""
        response = planner.delete("/api/ingredients/turkey_thigh")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INGREDIENT_IN_USE"

    def test_the_conflict_names_a_module_in_the_way(self, planner: TestClient) -> None:
        detail = planner.delete("/api/ingredients/turkey_thigh").json()["error"]["message"]
        assert "lunch_rice_noodles_turkey" in detail


class TestNotFound:
    def test_an_unknown_id_is_404_on_read(self, planner: TestClient) -> None:
        assert planner.get("/api/ingredients/not_a_food").status_code == 404

    def test_an_unknown_id_is_404_on_patch(self, planner: TestClient) -> None:
        assert (
            planner.patch("/api/ingredients/not_a_food", json={"is_staple": True}).status_code
            == 404
        )

    def test_an_unknown_id_is_404_on_delete(self, planner: TestClient) -> None:
        assert planner.delete("/api/ingredients/not_a_food").status_code == 404


class TestRoleBoundary:
    def test_a_follower_may_read_the_list(self, follower: TestClient) -> None:
        """Today and the shopping list both render ingredient names."""
        assert follower.get("/api/ingredients").status_code == 200

    def test_a_follower_may_read_one(self, follower: TestClient) -> None:
        assert follower.get("/api/ingredients/banana").status_code == 200

    @pytest.mark.parametrize(
        ("method", "path", "payload"),
        [
            ("post", "/api/ingredients", NEW),
            ("patch", "/api/ingredients/banana", {"is_staple": True}),
            ("delete", "/api/ingredients/banana", None),
        ],
    )
    def test_a_follower_gets_403_on_every_mutation(
        self, follower: TestClient, method: str, path: str, payload: dict | None
    ) -> None:
        call = getattr(follower, method)
        response = call(path, json=payload) if payload is not None else call(path)
        assert response.status_code == 403

    def test_an_unauthenticated_request_is_401(self, api: TestClient) -> None:
        assert api.get("/api/ingredients").status_code == 401


class TestSearchWorksInBothDatabases:
    """SQLite's lower() is ASCII-only.

    A SQL-side `lower(name) LIKE ...` matches Russian in Postgres and silently
    matches nothing in SQLite, so the search is done in Python. These pin that
    it stays that way.
    """

    def test_an_uppercase_cyrillic_query_matches(self, planner: TestClient) -> None:
        assert [i["id"] for i in planner.get("/api/ingredients", params={"q": "БАНАН"}).json()] == [
            "banana"
        ]

    def test_a_mixed_case_cyrillic_query_matches(self, planner: TestClient) -> None:
        assert [i["id"] for i in planner.get("/api/ingredients", params={"q": "бАнАн"}).json()] == [
            "banana"
        ]

    def test_a_partial_cyrillic_query_matches(self, planner: TestClient) -> None:
        ids = [i["id"] for i in planner.get("/api/ingredients", params={"q": "рыб"}).json()]
        assert "white_fish" in ids

    def test_the_router_does_not_use_sql_lower(self) -> None:
        """A regression guard with teeth: reintroducing lower() in SQL would
        pass every test above on Postgres and fail none of them locally."""
        import pathlib

        source = pathlib.Path("src/ration/api/routers/ingredients.py").read_text(encoding="utf-8")
        assert "func.lower" not in source


class TestDecimalRendering:
    def test_storage_padding_is_not_leaked_to_clients(self, planner: TestClient) -> None:
        """NUMERIC(12,4) stores 0.78 as 0.7800; a form field should not show that."""
        assert planner.get("/api/ingredients/white_fish").json()["yield_factor"] == "0.72"

    def test_whole_numbers_do_not_become_scientific_notation(self, planner: TestClient) -> None:
        """normalize() alone turns Decimal("100") into 1E+2."""
        body = planner.post(
            "/api/ingredients",
            json=dict(
                NEW,
                names={"ru": "Вода"},
                kcal_per_100g="100",
                yield_factor="1",
                yield_source="as_purchased",
            ),
        ).json()
        assert body["kcal_per_100g"] == "100"

    def test_a_unit_yield_renders_as_one(self, planner: TestClient) -> None:
        assert planner.get("/api/ingredients/banana").json()["yield_factor"] == "1"


class TestAliasUniqueness:
    """Found by QA on #23: a duplicate alias escaped as a 500.

    `UNIQUE (locale, alias)` is right — two ingredients answering to "cod" make
    alias search ambiguous. The defect was that the constraint fired on flush,
    after the handler returned, so the planner got a 500 instead of being told
    which ingredient already holds the alias.
    """

    def test_creating_with_an_alias_another_holds_is_409(self, planner: TestClient) -> None:
        planner.post("/api/ingredients", json=NEW)
        response = planner.post("/api/ingredients", json=dict(NEW, names={"ru": "Пикша"}))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ALIAS_IN_USE"

    def test_the_conflict_names_the_ingredient_holding_it(self, planner: TestClient) -> None:
        planner.post("/api/ingredients", json=NEW)
        message = planner.post("/api/ingredients", json=dict(NEW, names={"ru": "Пикша"})).json()[
            "error"
        ]["message"]
        assert "treska" in message and "cod" in message

    def test_patching_in_a_taken_alias_is_409(self, planner: TestClient) -> None:
        planner.post("/api/ingredients", json=NEW)
        assert (
            planner.patch("/api/ingredients/banana", json={"aliases": ["cod"]}).status_code == 409
        )

    def test_keeping_your_own_alias_on_patch_is_fine(self, planner: TestClient) -> None:
        """The check must not treat an ingredient's existing alias as a clash."""
        planner.post("/api/ingredients", json=NEW)
        response = planner.patch("/api/ingredients/treska", json={"aliases": ["cod", "белая рыба"]})
        assert response.status_code == 200
        assert set(response.json()["aliases"]) == {"cod", "белая рыба"}

    def test_a_repeated_alias_within_one_request_is_422(self, planner: TestClient) -> None:
        response = planner.post(
            "/api/ingredients", json=dict(NEW, names={"ru": "Сайда"}, aliases=["x", "x"])
        )
        assert response.status_code == 422
        assert response.json()["error"]["details"][0]["field"] == "aliases"

    def test_no_mutation_can_return_a_500(self, planner: TestClient) -> None:
        """The shape of the original defect: a constraint escaping as a 500."""
        planner.post("/api/ingredients", json=NEW)
        for response in (
            planner.post("/api/ingredients", json=dict(NEW, names={"ru": "Пикша"})),
            planner.patch("/api/ingredients/banana", json={"aliases": ["cod"]}),
        ):
            assert response.status_code < 500
