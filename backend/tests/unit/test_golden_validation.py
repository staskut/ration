"""What the reference plan actually reports, and why that is not nothing.

This test used to assert the reference week validated cleanly. It no longer
does, and the change is the point.

The catalog previously carried nutrition values tuned until every dish matched
the figure section 9 states for it. Under those values the week could not fail,
because the instrument had been bent to agree with the thing it was measuring.
Switching to reference values (docs/decisions.md D1) removed that, and the week
now reports two errors and eleven warnings — all of them true.

The most useful one is structural: days 0 and 3 fall about 100 kcal short, and
both are training days. The plan feeds least on the days that end with
resistance training. Nothing in a self-consistent fixture could have surfaced
that.

The expected set below is therefore an assertion about a real week, not a
regression lock. If the catalog improves and a finding disappears, that is
progress — update this list and say so in the commit.

The perturbation tests still matter as much as the rest: a validator that
reports nothing is indistinguishable from one that checks nothing.
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


# Every finding the reference week produces, as (level, code, day, slot).
EXPECTED = {
    # Both training days come in about 100 kcal short.
    ("error", "DAY_KCAL_OUT_OF_RANGE", 0, None),
    ("error", "DAY_KCAL_OUT_OF_RANGE", 3, None),
    ("warning", "SLOT_OUT_OF_BUDGET", 0, "breakfast"),
    ("warning", "SLOT_OUT_OF_BUDGET", 0, "dinner"),
    ("warning", "SLOT_OUT_OF_BUDGET", 2, "breakfast"),
    ("warning", "SLOT_OUT_OF_BUDGET", 2, "dinner"),
    ("warning", "SLOT_OUT_OF_BUDGET", 3, "breakfast"),
    ("warning", "SLOT_OUT_OF_BUDGET", 3, "dinner"),
    ("warning", "SLOT_OUT_OF_BUDGET", 3, "lunch"),
    ("warning", "SLOT_OUT_OF_BUDGET", 4, "lunch"),
    ("warning", "SLOT_OUT_OF_BUDGET", 5, "breakfast"),
    ("warning", "SLOT_OUT_OF_BUDGET", 5, "dinner"),
    ("warning", "SLOT_OUT_OF_BUDGET", 5, "lunch"),
    ("info", "DAY_UNPLANNED", 6, None),
}


class TestWhatTheReferenceWeekReports:
    def test_the_finding_set_is_exactly_as_expected(self) -> None:
        """The full set, so a new finding type cannot slip in unnoticed the way
        a 'no errors' check would let it."""
        actual = {(f.level, f.code, f.day_index, f.slot) for f in findings()}
        assert actual == EXPECTED

    def test_the_only_errors_are_the_two_short_days(self) -> None:
        errors = [(f.code, f.day_index) for f in findings() if f.level == "error"]
        assert errors == [("DAY_KCAL_OUT_OF_RANGE", 0), ("DAY_KCAL_OUT_OF_RANGE", 3)]

    def test_both_short_days_are_training_days(self) -> None:
        """The finding worth acting on: the week feeds least on the two days
        that end with resistance training."""
        short = {f.day_index for f in findings() if f.code == "DAY_KCAL_OUT_OF_RANGE"}
        templates = {REFERENCE.plan.days[i].day_template for i in short}
        assert templates == {"training"}

    def test_no_day_falls_below_the_protein_floor(self) -> None:
        """Calories drift; protein does not. The plan's actual purpose holds."""
        assert "DAY_PROTEIN_BELOW_MIN" not in codes_of(findings())

    def test_protein_ceilings_produce_no_findings(self) -> None:
        """Protein is a floor, not a band (docs/decisions.md D2). Several days
        run well above the stated 110 g; none of that is a problem."""
        protein_findings = [
            f
            for f in findings()
            if f.code == "SLOT_OUT_OF_BUDGET" and f.params.get("metric") == "protein_g"
        ]
        assert protein_findings == []

    def test_no_rule_violations_only_budget_drift(self) -> None:
        """Nothing is excluded, over-frequent, or on a forbidden day. The week is
        structurally sound; it just misses its calorie bands."""
        structural = {
            "EXCLUDED_INGREDIENT",
            "CAUTION_THRESHOLD_EXCEEDED",
            "FREQUENCY_EXCEEDED",
            "TEMPLATE_GATE_VIOLATED",
            "MULTIPLE_MAIN_ENTRIES",
            "BATCH_NOT_CONSECUTIVE",
        }
        assert structural.isdisjoint(set(codes_of(findings())))

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
def test_each_day_reports_only_what_is_expected(day_index: int) -> None:
    """Names the day that changed, rather than one failure for the whole week."""
    actual = {(f.level, f.code, f.slot) for f in findings() if f.day_index == day_index}
    expected = {(lvl, code, slot) for lvl, code, day, slot in EXPECTED if day == day_index}
    assert actual == expected
