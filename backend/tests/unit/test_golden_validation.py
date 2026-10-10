"""The reference plan validates cleanly.

A real week, built by a person against the rules in sections 1, 4, 5 and 7 of
docs/sample-plan-6-days.md, should produce no errors and no warnings. If it
does, either the engine is wrong or the week was — and since the week was eaten,
the engine is the first suspect.

The perturbation tests below matter as much as the clean one. A validator that
reports nothing is indistinguishable from a validator that checks nothing, so
each rule is shown to fire when the fixture is bent to break it.
"""

from dataclasses import replace
from decimal import Decimal

import pytest

from ration.domain.types import IngredientRule, Plan, PlanEntry
from ration.domain.validation import validate
from ration.seed import load_reference

REFERENCE = load_reference()


def findings(plan: Plan | None = None, profile=None):  # type: ignore[no-untyped-def]
    return validate(
        plan or REFERENCE.plan,
        profile or REFERENCE.profile,
        REFERENCE.catalog,
    )


def codes_of(result) -> list[str]:  # type: ignore[no-untyped-def]
    return [f.code for f in result]


def move_entry(module_id: str, to_day: int) -> Plan:
    """Relocate the first entry using a module onto another day."""
    source = next(
        (d, e) for d in REFERENCE.plan.days for e in d.entries if e.module_id == module_id
    )
    from_day, entry = source
    days = []
    for day in REFERENCE.plan.days:
        if day.day_index == from_day.day_index:
            days.append(replace(day, entries=tuple(e for e in day.entries if e.id != entry.id)))
        elif day.day_index == to_day:
            days.append(replace(day, entries=(*day.entries, replace(entry, position=9))))
        else:
            days.append(day)
    return replace(REFERENCE.plan, days=tuple(days))


class TestTheReferenceWeekIsClean:
    def test_no_errors(self) -> None:
        errors = [f for f in findings() if f.level == "error"]
        assert errors == [], f"unexpected errors: {[(f.code, f.day_index) for f in errors]}"

    def test_no_warnings(self) -> None:
        warnings = [f for f in findings() if f.level == "warning"]
        assert warnings == [], f"unexpected warnings: {[(f.code, f.day_index) for f in warnings]}"

    def test_the_only_finding_is_the_unplanned_seventh_day(self) -> None:
        """Asserts the full set, so a new finding type appearing cannot pass
        unnoticed the way a 'no errors' check would let it."""
        result = findings()
        assert len(result) == 1
        assert result[0].code == "DAY_UNPLANNED"
        assert result[0].day_index == 6
        assert result[0].level == "info"

    def test_the_unplanned_day_is_not_also_reported_slot_by_slot(self) -> None:
        assert "SLOT_EMPTY" not in codes_of(findings())

    def test_days_without_a_treat_are_not_reported_as_incomplete(self) -> None:
        """Three treats a week is the rule, so four treatless days are correct."""
        treat_days = {
            d.day_index for d in REFERENCE.plan.days if any(e.slot == "treat" for e in d.entries)
        }
        assert len(treat_days) == 3


class TestTheValidatorActuallyBites:
    """Each rule, shown firing against a deliberately bent fixture."""

    def test_wine_on_a_training_day_is_caught(self) -> None:
        # Day 0 is a training day; the alcohol rule blocks it there.
        assert "TEMPLATE_GATE_VIOLATED" in codes_of(findings(move_entry("treat_wine", 0)))

    def test_a_fourth_treat_breaks_the_weekly_limit(self) -> None:
        day = REFERENCE.plan.days[0]
        extra = PlanEntry(id="extra", slot="treat", module_id="treat_ice_cream", position=9)
        bent = replace(
            REFERENCE.plan,
            days=tuple(
                replace(d, entries=(*d.entries, extra)) if d.day_index == 0 else d
                for d in REFERENCE.plan.days
            ),
        )
        assert day is not None
        assert "FREQUENCY_EXCEEDED" in codes_of(findings(bent))

    def test_a_third_salted_fish_dinner_breaks_its_limit(self) -> None:
        extra = PlanEntry(id="extra", slot="dinner", module_id="dinner_herring_cottage", position=9)
        bent = replace(
            REFERENCE.plan,
            days=tuple(
                replace(d, entries=(*d.entries, extra)) if d.day_index == 6 else d
                for d in REFERENCE.plan.days
            ),
        )
        tags = [f.params.get("tag") for f in findings(bent) if f.code == "FREQUENCY_EXCEEDED"]
        assert "salted_fish" in tags

    def test_a_tighter_calorie_target_is_caught(self) -> None:
        profile = replace(REFERENCE.profile, daily_kcal_target=Decimal(1200))
        assert "DAY_KCAL_OUT_OF_RANGE" in codes_of(findings(profile=profile))

    def test_a_higher_protein_floor_is_caught(self) -> None:
        profile = replace(REFERENCE.profile, daily_protein_min=Decimal(200))
        assert "DAY_PROTEIN_BELOW_MIN" in codes_of(findings(profile=profile))

    def test_excluding_an_ingredient_the_plan_uses_is_caught(self) -> None:
        profile = replace(
            REFERENCE.profile,
            ingredient_rules=(IngredientRule("spinach", "excluded"),),
        )
        assert "EXCLUDED_INGREDIENT" in codes_of(findings(profile=profile))

    def test_a_low_caution_threshold_is_caught(self) -> None:
        profile = replace(
            REFERENCE.profile,
            ingredient_rules=(IngredientRule("spinach", "caution", threshold_g=Decimal(10)),),
        )
        assert "CAUTION_THRESHOLD_EXCEEDED" in codes_of(findings(profile=profile))

    def test_breaking_a_batch_lunch_run_is_caught(self) -> None:
        # The noodle lunch runs days 0-2; moving one of them to day 6 leaves a gap.
        bent = move_entry("lunch_rice_noodles_turkey", 6)
        assert "BATCH_NOT_CONSECUTIVE" in codes_of(findings(bent))

    def test_a_second_main_in_a_slot_is_caught(self) -> None:
        extra = PlanEntry(id="extra", slot="dinner", module_id="dinner_squid_pepper", position=9)
        bent = replace(
            REFERENCE.plan,
            days=tuple(
                replace(d, entries=(*d.entries, extra)) if d.day_index == 0 else d
                for d in REFERENCE.plan.days
            ),
        )
        assert "MULTIPLE_MAIN_ENTRIES" in codes_of(findings(bent))


@pytest.mark.parametrize("day_index", range(6))
def test_every_planned_day_is_individually_clean(day_index: int) -> None:
    """Names the day that broke, rather than reporting one failure for the week."""
    problems = [
        f for f in findings() if f.day_index == day_index and f.level in {"error", "warning"}
    ]
    assert problems == [], f"day {day_index}: {[f.code for f in problems]}"
