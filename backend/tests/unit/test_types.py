"""Domain types are frozen, validate their own invariants, and never use floats."""

import ast
import pathlib
from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from ration.domain.types import (
    DAYS_PER_PLAN,
    Catalog,
    Feedback,
    FrequencyRule,
    Ingredient,
    IngredientRule,
    Module,
    ModuleLine,
    Plan,
    PlanDay,
    PlanEntry,
    Profile,
    SlotBudget,
    Totals,
)

DOMAIN = pathlib.Path(__file__).parents[2] / "src" / "ration" / "domain"


def ingredient(ingredient_id: str = "turkey_thigh", **overrides: object) -> Ingredient:
    defaults: dict[str, object] = {
        "names": {"ru": "Бедро индейки"},
        "kcal_per_100g": Decimal("185"),
        "protein_per_100g": Decimal("24"),
        "yield_factor": Decimal("0.67"),
    }
    return Ingredient(id=ingredient_id, **(defaults | overrides))  # type: ignore[arg-type]


def module(module_id: str = "lunch_noodles", **overrides: object) -> Module:
    defaults: dict[str, object] = {
        "name": "Рисовая лапша с индейкой",
        "slot": "lunch",
        "lines": (ModuleLine("turkey_thigh", Decimal("120")),),
    }
    return Module(id=module_id, **(defaults | overrides))  # type: ignore[arg-type]


def plan_days(entries_on_day_0: tuple[PlanEntry, ...] = ()) -> tuple[PlanDay, ...]:
    return tuple(
        PlanDay(
            day_index=i,
            date=date(2026, 10, 12 + i),
            entries=entries_on_day_0 if i == 0 else (),
        )
        for i in range(DAYS_PER_PLAN)
    )


class TestImmutability:
    def test_dataclasses_reject_assignment(self) -> None:
        with pytest.raises((FrozenInstanceError, AttributeError)):
            ingredient().kcal_per_100g = Decimal(1)  # type: ignore[misc]

    def test_ingredient_names_cannot_be_mutated(self) -> None:
        with pytest.raises(TypeError):
            ingredient().names["en"] = "Turkey thigh"  # type: ignore[index]

    def test_catalog_mappings_cannot_be_mutated(self) -> None:
        catalog = Catalog(ingredients={"turkey_thigh": ingredient()})
        with pytest.raises(TypeError):
            catalog.ingredients["x"] = ingredient("x")  # type: ignore[index]

    def test_catalog_copies_its_input_so_later_edits_do_not_leak_in(self) -> None:
        source = {"turkey_thigh": ingredient()}
        catalog = Catalog(ingredients=source)
        source["smuggled"] = ingredient("smuggled")
        assert "smuggled" not in catalog.ingredients


class TestNoFloats:
    def test_domain_never_references_float(self) -> None:
        """Rigorous version of "no floats": parse the AST rather than grep, so
        the word appearing in a docstring does not count and a float literal
        cannot hide behind one."""
        offenders: list[str] = []
        for path in DOMAIN.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "float":
                    offenders.append(f"{path.name}:{node.lineno} uses float")
                if isinstance(node, ast.Constant) and type(node.value) is float:
                    offenders.append(f"{path.name}:{node.lineno} has a float literal")
        assert offenders == []


class TestInvariants:
    @pytest.mark.parametrize("bad", [Decimal(0), Decimal("-0.5"), Decimal("2.5")])
    def test_yield_factor_must_be_in_range(self, bad: Decimal) -> None:
        with pytest.raises(ValueError, match="yield_factor"):
            ingredient(yield_factor=bad)

    def test_yield_factor_of_one_is_allowed_for_uncooked_items(self) -> None:
        assert ingredient(yield_factor=Decimal(1)).yield_factor == Decimal(1)

    def test_module_line_must_have_a_positive_weight(self) -> None:
        with pytest.raises(ValueError, match="grams_cooked"):
            ModuleLine("turkey_thigh", Decimal(0))

    def test_module_must_have_lines(self) -> None:
        with pytest.raises(ValueError, match="no lines"):
            module(lines=())

    def test_batch_portions_cannot_exceed_the_week(self) -> None:
        with pytest.raises(ValueError, match="batch_portions"):
            module(batch_portions=DAYS_PER_PLAN + 1)

    @pytest.mark.parametrize("bad", [Decimal("0.4"), Decimal("1.6")])
    def test_portion_factor_is_bounded(self, bad: Decimal) -> None:
        with pytest.raises(ValueError, match="portion_factor"):
            PlanEntry(id="e1", slot="dinner", module_id="m", portion_factor=bad)

    def test_a_plan_has_exactly_seven_days(self) -> None:
        with pytest.raises(ValueError, match="exactly 7 days"):
            Plan(
                id="p",
                name="Week 1",
                profile_id="pr",
                start_date=date(2026, 10, 12),
                days=plan_days()[:6],
            )

    def test_plan_days_must_be_indexed_in_order(self) -> None:
        shuffled = plan_days()[::-1]
        with pytest.raises(ValueError, match="indexed"):
            Plan(
                id="p",
                name="Week 1",
                profile_id="pr",
                start_date=date(2026, 10, 12),
                days=shuffled,
            )

    def test_caution_rule_requires_a_threshold(self) -> None:
        with pytest.raises(ValueError, match="threshold_g"):
            IngredientRule("hummus", "caution")

    def test_bloating_is_bounded_to_the_documented_scale(self) -> None:
        with pytest.raises(ValueError, match="bloating"):
            Feedback("e1", bloating=4)


class TestBehaviour:
    def test_totals_add_and_scale(self) -> None:
        a = Totals(Decimal(100), Decimal(10))
        assert a + Totals(Decimal(50), Decimal(5)) == Totals(Decimal(150), Decimal(15))
        assert a.scaled_by(Decimal("0.5")) == Totals(Decimal(50), Decimal(5))

    def test_name_falls_back_when_the_locale_is_missing(self) -> None:
        assert ingredient().name("en") == "Бедро индейки"

    def test_entries_in_slot_filters_by_slot(self) -> None:
        main = PlanEntry(id="a", slot="dinner", module_id="fish")
        side = PlanEntry(id="b", slot="dinner", module_id="pumpkin", position=1)
        other = PlanEntry(id="c", slot="lunch", module_id="noodles")
        day = PlanDay(day_index=0, date=date(2026, 10, 12), entries=(main, side, other))
        assert day.entries_in("dinner") == (main, side)

    def test_a_day_with_no_entries_is_unplanned(self) -> None:
        assert not PlanDay(day_index=0, date=date(2026, 10, 12)).is_planned

    def test_profile_lookups_return_none_when_absent(self) -> None:
        profile = Profile(
            id="p",
            name="Reference",
            daily_kcal_target=Decimal(1700),
            daily_protein_min=Decimal(105),
            daily_protein_target=Decimal(110),
            slot_budgets=(
                SlotBudget("dinner", Decimal(470), Decimal(495), Decimal(35), Decimal(42)),
            ),
        )
        assert profile.budget_for("dinner") is not None
        assert profile.budget_for("breakfast") is None
        assert profile.rule_for("nothing") is None

    def test_frequency_rule_defaults_to_no_limit(self) -> None:
        rule = FrequencyRule(tag="liver")
        assert rule.max_per_week is None
        assert rule.blocked_on_templates == frozenset()

    def test_catalog_lookup_names_the_missing_id(self) -> None:
        with pytest.raises(KeyError, match="Unknown ingredient: ghost"):
            Catalog().ingredient("ghost")

    def test_all_entries_flattens_the_week(self) -> None:
        entry = PlanEntry(id="e", slot="lunch", module_id="noodles")
        plan = Plan(
            id="p",
            name="Week 1",
            profile_id="pr",
            start_date=date(2026, 10, 12),
            days=plan_days((entry,)),
        )
        assert plan.all_entries == (entry,)
