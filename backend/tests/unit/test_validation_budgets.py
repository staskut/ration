"""Daily and per-slot budget checks."""

from ration.domain.validation import validate
from tests.unit.conftest import (
    budget,
    make_catalog,
    make_entry,
    make_module,
    make_plan,
    make_profile,
)

# These tests assert on budget findings only. Structural checks (#15) add
# informational SLOT_EMPTY and DAY_UNPLANNED findings to the same result, and a
# bare "no findings at all" assertion would couple every budget test to them.
BUDGET_CODES = {
    "DAY_KCAL_OUT_OF_RANGE",
    "DAY_PROTEIN_BELOW_MIN",
    "SLOT_OUT_OF_BUDGET",
}


def budget_codes(findings) -> list[str]:  # type: ignore[no-untyped-def]
    return [f.code for f in findings if f.code in BUDGET_CODES]


# 100 g of "plain" is 100 kcal and 10 g protein; "rich" is 500 kcal and 50 g.
PLAIN = make_module("plain_dinner", grams="1000")  # 1000 kcal, 100 g protein
CATALOG = make_catalog(PLAIN)


def plan_with(grams: str):  # type: ignore[no-untyped-def]
    module = make_module("m", grams=grams)
    return make_plan({0: (make_entry("m"),)}), make_catalog(module)


class TestDailyCalories:
    def test_a_day_on_target_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1000")
        assert budget_codes(validate(plan, make_profile(), catalog)) == []

    def test_a_day_exactly_on_the_lower_bound_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("950")
        assert "DAY_KCAL_OUT_OF_RANGE" not in codes(validate(plan, make_profile(), catalog))

    def test_a_day_exactly_on_the_upper_bound_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1050")
        assert "DAY_KCAL_OUT_OF_RANGE" not in codes(validate(plan, make_profile(), catalog))

    def test_a_day_over_the_tolerance_is_an_error(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1051")
        findings = validate(plan, make_profile(), catalog)
        assert "DAY_KCAL_OUT_OF_RANGE" in codes(findings)
        assert findings[0].level == "error"

    def test_a_day_under_the_tolerance_is_an_error(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("500")
        assert "DAY_KCAL_OUT_OF_RANGE" in codes(validate(plan, make_profile(), catalog))

    def test_the_finding_carries_the_numbers_not_a_sentence(self) -> None:
        plan, catalog = plan_with("1200")
        finding = next(
            f for f in validate(plan, make_profile(), catalog) if f.code == "DAY_KCAL_OUT_OF_RANGE"
        )
        assert finding.params == {"actual": "1200.0", "min": "950.0", "max": "1050.0"}
        assert finding.message_key == "validation.day_kcal_out_of_range"
        assert finding.day_index == 0


class TestDailyProtein:
    def test_protein_at_the_minimum_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1000")  # 100 g protein
        profile = make_profile(protein_min="100")
        assert "DAY_PROTEIN_BELOW_MIN" not in codes(validate(plan, profile, catalog))

    def test_protein_below_the_minimum_is_an_error(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1000")
        profile = make_profile(protein_min="150")
        assert "DAY_PROTEIN_BELOW_MIN" in codes(validate(plan, profile, catalog))

    def test_protein_above_the_minimum_is_never_flagged(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1000")
        profile = make_profile(protein_min="10")
        assert "DAY_PROTEIN_BELOW_MIN" not in codes(validate(plan, profile, catalog))


class TestUnplannedDays:
    def test_an_unplanned_day_produces_no_budget_findings(self, codes) -> None:  # type: ignore[no-untyped-def]
        """A day with no food is an in-progress week, not a starving one.

        Structural checks report the empty week separately and at info level;
        this asserts only that no *budget* finding appears.
        """
        plan = make_plan({})
        assert budget_codes(validate(plan, make_profile(), CATALOG)) == []


class TestSlotBudgets:
    def test_a_slot_inside_its_budget_passes(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1000")
        profile = make_profile(budgets=(budget("dinner", kcal=("900", "1100")),))
        assert "SLOT_OUT_OF_BUDGET" not in codes(validate(plan, profile, catalog))

    def test_a_slot_over_its_calorie_budget_is_a_warning(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1000")
        profile = make_profile(budgets=(budget("dinner", kcal=("100", "500")),))
        findings = [f for f in validate(plan, profile, catalog) if f.code == "SLOT_OUT_OF_BUDGET"]
        assert findings[0].level == "warning"
        assert findings[0].params["metric"] == "kcal"

    def test_calorie_and_protein_breaches_are_reported_separately(self) -> None:
        plan, catalog = plan_with("1000")
        profile = make_profile(
            budgets=(budget("dinner", kcal=("100", "500"), protein=("0", "20")),)
        )
        metrics = {
            f.params["metric"]
            for f in validate(plan, profile, catalog)
            if f.code == "SLOT_OUT_OF_BUDGET"
        }
        assert metrics == {"kcal", "protein_g"}

    def test_a_slot_can_breach_on_protein_alone(self) -> None:
        plan, catalog = plan_with("1000")
        profile = make_profile(budgets=(budget("dinner", kcal=("0", "5000"), protein=("0", "20")),))
        metrics = [
            f.params["metric"]
            for f in validate(plan, profile, catalog)
            if f.code == "SLOT_OUT_OF_BUDGET"
        ]
        assert metrics == ["protein_g"]

    def test_two_entries_each_fine_can_breach_when_summed(self, codes) -> None:  # type: ignore[no-untyped-def]
        """The reason budgets apply to a slot's sum: a main plus a side.

        Each entry is 300 kcal and inside a 0-500 budget on its own; together
        they are 600 and are not.
        """
        main = make_module("main", grams="300")
        side = make_module("side", role="side", grams="300")
        catalog = make_catalog(main, side)
        plan = make_plan(
            {0: (make_entry("main"), make_entry("side", position=1))},
        )
        profile = make_profile(kcal_target="600", budgets=(budget("dinner", kcal=("0", "500")),))
        assert "SLOT_OUT_OF_BUDGET" in codes(validate(plan, profile, catalog))

    def test_a_slot_with_no_budget_is_not_checked(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan, catalog = plan_with("1000")
        profile = make_profile(budgets=(budget("breakfast", kcal=("0", "1")),))
        assert "SLOT_OUT_OF_BUDGET" not in codes(validate(plan, profile, catalog))


class TestOrdering:
    def test_errors_sort_before_warnings_before_info(self) -> None:
        plan, catalog = plan_with("2000")
        profile = make_profile(budgets=(budget("dinner", kcal=("0", "100")),))
        findings = validate(plan, profile, catalog)
        levels = [f.level for f in findings]
        assert {"error", "warning", "info"} <= set(levels), "needs all three to be a real test"
        assert levels == sorted(levels, key=["error", "warning", "info"].index)
