"""The staged incident: the refusals, and the failure it stages (#60).

Two things are tested here and the first matters more than the second. A
staging mechanism that could be aimed at the real deployment is worse than
having no staged incident at all, so each refusal in
`observability/incident/stage_incident.py` has a test that it refuses, the way
`test_seed.py` covers the seed's refusal to run in production.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from ration.domain.shopping import convert_to_raw, expand_entries, shopping_list
from ration.domain.types import Catalog, Ingredient, Module, ModuleLine
from ration.domain.units import Dimension, UnrecognisedUnitError, dimension_for
from ration.seed import load_reference

from .conftest import make_entry, make_plan

REPO = Path(__file__).parents[3]
SCRIPT = REPO / "observability" / "incident" / "stage_incident.py"


def _staging_module() -> Any:
    """Load the script by path: it lives outside the package, by design.

    It is standard library only and run with `python3 observability/...`, so it
    is not importable as `ration.something`. Loading it here rather than
    shelling out keeps the refusals unit-testable.
    """
    spec = importlib.util.spec_from_file_location("stage_incident", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


staging = _staging_module()


class TestItRefusesAnythingThatIsNotALocalStack:
    def test_it_refuses_a_production_environment(self) -> None:
        with pytest.raises(SystemExit) as refused:
            staging.check_environment("production", "http://localhost:8010")
        assert "production" in str(refused.value)

    def test_it_refuses_a_production_environment_however_it_is_spelled(self) -> None:
        for spelling in ("Production", " PRODUCTION ", "production"):
            with pytest.raises(SystemExit):
                staging.check_environment(spelling, "http://localhost:8010")

    def test_it_refuses_a_remote_api(self) -> None:
        with pytest.raises(SystemExit) as refused:
            staging.check_url("https://ration-plan.fly.dev")
        assert "ration-plan.fly.dev" in str(refused.value)

    def test_it_refuses_a_staging_api_too(self) -> None:
        """Staging is somebody's demo, not a target."""
        with pytest.raises(SystemExit):
            staging.check_url("https://ration-plan-staging.fly.dev")

    def test_it_refuses_a_database_that_is_not_local(self) -> None:
        """The realistic mistake: a Neon DSN already exported in the shell."""
        with pytest.raises(SystemExit) as refused:
            staging.check_database_url(
                "postgresql+psycopg://user:pw@ep-cool-name.eu-central-1.aws.neon.tech/ration",
                "http://localhost:8010",
            )
        assert "neon.tech" in str(refused.value)

    def test_it_refuses_a_compose_file_that_is_not_the_local_stack(self) -> None:
        with pytest.raises(SystemExit) as refused:
            staging.check_compose_file(Path("/somewhere/else/compose.yaml"))
        assert "compose" in str(refused.value)

    def test_it_allows_the_local_stack(self) -> None:
        staging.check_url("http://localhost:8010")
        staging.check_url("http://127.0.0.1:8000")
        staging.check_environment("development", "http://localhost:8010")
        staging.check_database_url(
            "postgresql+psycopg://ration:ration-dev@db:5432/ration", "http://localhost:8010"
        )
        staging.check_compose_file(REPO / "observability" / "compose.yaml")

    def test_every_refusal_exits_non_zero(self) -> None:
        """`SystemExit` with a message exits 1, so a runbook step fails loudly."""
        refused = staging.Refused("because", "a target")
        assert refused.code != 0
        assert "a target" in str(refused.code)


class TestTheFailureItStages:
    """An unrecognised unit reaching the raw-weight conversion, as HLD §7 says."""

    @staticmethod
    def _catalog(unit: str | None) -> Catalog:
        return Catalog(
            ingredients={
                "olive_oil": Ingredient(
                    id="olive_oil",
                    names={"ru": "Оливковое масло"},
                    kcal_per_100g=Decimal(884),
                    protein_per_100g=Decimal(0),
                    package_size=Decimal(500),
                    package_unit=unit,
                )
            },
            modules={
                "dinner": Module(
                    id="dinner",
                    name="dinner",
                    slot="dinner",
                    role="main",
                    batch_portions=1,
                    lines=(ModuleLine("olive_oil", Decimal(10)),),
                )
            },
        )

    def _plan(self) -> Any:
        return make_plan({0: (make_entry("dinner"),)})

    def test_an_unmodelled_unit_raises_at_the_conversion(self) -> None:
        catalog = self._catalog("tbsp")
        cooked = expand_entries(self._plan(), catalog)

        with pytest.raises(UnrecognisedUnitError) as raised:
            convert_to_raw(cooked, resolve_units=True)

        assert raised.value.unit == "tbsp"
        assert raised.value.ingredient_id == "olive_oil"

    def test_the_same_catalog_passes_with_the_check_off(self) -> None:
        """Which is why the row can sit there until a release turns it on."""
        catalog = self._catalog("tbsp")
        lines = shopping_list(self._plan(), catalog)
        assert len(lines) == 1

    def test_the_three_modelled_units_and_no_unit_are_fine(self) -> None:
        for unit in ("g", "ml", "pcs", None):
            catalog = self._catalog(unit)
            assert shopping_list(self._plan(), catalog, resolve_units=True)

    def test_the_message_names_the_row_which_is_why_it_is_never_logged(self) -> None:
        """The reason #56 and #57 record the class and not the message."""
        error = UnrecognisedUnitError("tbsp", "olive_oil")
        assert "olive_oil" in str(error)

    def test_dimension_for_maps_the_three_it_models(self) -> None:
        assert dimension_for("g", "x") is Dimension.MASS
        assert dimension_for("ml", "x") is Dimension.VOLUME
        assert dimension_for("pcs", "x") is Dimension.COUNT
        assert dimension_for(None, "x") is None


class TestTheReferencePlanIsUnaffected:
    def test_the_reference_catalog_holds_no_unmodelled_unit(self) -> None:
        """So no golden expectation moves when the check is on."""
        reference = load_reference()
        for ingredient in reference.catalog.ingredients.values():
            assert dimension_for(ingredient.package_unit, ingredient.id) is not None or (
                ingredient.package_unit is None
            )

    def test_the_reference_shopping_list_is_identical_with_the_check_on(self) -> None:
        reference = load_reference()
        assert shopping_list(reference.plan, reference.catalog, resolve_units=True) == (
            shopping_list(reference.plan, reference.catalog)
        )
