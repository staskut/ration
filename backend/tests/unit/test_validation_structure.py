"""Structural findings: slot shape, batch runs, and what is still missing."""

from ration.domain.validation import validate
from tests.unit.conftest import (
    budget,
    make_catalog,
    make_entry,
    make_module,
    make_plan,
    make_profile,
)

MAIN_A = make_module("main_a")
MAIN_B = make_module("main_b")
SIDE_A = make_module("side_a", role="side")
SIDE_B = make_module("side_b", role="side")
BATCH = make_module("batch", slot="lunch", batch_portions=3)

DINNER_ONLY = make_profile(budgets=(budget("dinner"),))


class TestSlotShape:
    def test_two_mains_in_one_slot_is_an_error(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({0: (make_entry("main_a"), make_entry("main_b", position=1))})
        findings = validate(plan, DINNER_ONLY, make_catalog(MAIN_A, MAIN_B))
        assert "MULTIPLE_MAIN_ENTRIES" in codes(findings)

    def test_one_main_with_several_sides_is_fine(self, codes) -> None:  # type: ignore[no-untyped-def]
        """The arrangement the pilot actually used: protein plus a side."""
        plan = make_plan(
            {
                0: (
                    make_entry("main_a"),
                    make_entry("side_a", position=1),
                    make_entry("side_b", position=2),
                )
            }
        )
        findings = validate(plan, DINNER_ONLY, make_catalog(MAIN_A, SIDE_A, SIDE_B))
        assert "MULTIPLE_MAIN_ENTRIES" not in codes(findings)

    def test_sides_alone_are_not_flagged(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({0: (make_entry("side_a"), make_entry("side_b", position=1))})
        findings = validate(plan, DINNER_ONLY, make_catalog(SIDE_A, SIDE_B))
        assert "MULTIPLE_MAIN_ENTRIES" not in codes(findings)

    def test_the_finding_names_the_slot_and_the_count(self) -> None:
        plan = make_plan({0: (make_entry("main_a"), make_entry("main_b", position=1))})
        finding = next(
            f
            for f in validate(plan, DINNER_ONLY, make_catalog(MAIN_A, MAIN_B))
            if f.code == "MULTIPLE_MAIN_ENTRIES"
        )
        assert finding.slot == "dinner"
        assert finding.params["actual"] == "2"
        assert finding.level == "error"


class TestBatchRuns:
    def test_consecutive_days_pass(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({i: (make_entry("batch", "lunch"),) for i in (0, 1, 2)})
        findings = validate(plan, make_profile(budgets=(budget("lunch"),)), make_catalog(BATCH))
        assert "BATCH_NOT_CONSECUTIVE" not in codes(findings)

    def test_a_gap_is_a_warning(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({i: (make_entry("batch", "lunch"),) for i in (0, 1, 4)})
        findings = validate(plan, make_profile(budgets=(budget("lunch"),)), make_catalog(BATCH))
        assert "BATCH_NOT_CONSECUTIVE" in codes(findings)

    def test_the_warning_lists_the_days(self) -> None:
        plan = make_plan({i: (make_entry("batch", "lunch"),) for i in (0, 1, 4)})
        finding = next(
            f
            for f in validate(plan, make_profile(budgets=(budget("lunch"),)), make_catalog(BATCH))
            if f.code == "BATCH_NOT_CONSECUTIVE"
        )
        assert finding.params["days"] == "0,1,4"
        assert finding.level == "warning"

    def test_fewer_appearances_than_portions_is_not_a_finding(self, codes) -> None:  # type: ignore[no-untyped-def]
        """Cooking ahead and eating less is a choice, not a mistake."""
        plan = make_plan({0: (make_entry("batch", "lunch"),)})
        findings = validate(plan, make_profile(budgets=(budget("lunch"),)), make_catalog(BATCH))
        assert "BATCH_NOT_CONSECUTIVE" not in codes(findings)

    def test_a_non_batch_module_is_never_checked(self, codes) -> None:  # type: ignore[no-untyped-def]
        plan = make_plan({i: (make_entry("main_a"),) for i in (0, 3, 6)})
        findings = validate(plan, DINNER_ONLY, make_catalog(MAIN_A))
        assert "BATCH_NOT_CONSECUTIVE" not in codes(findings)


class TestIncompleteWeeks:
    def test_an_unplanned_day_reports_only_itself(self) -> None:
        """Not five SLOT_EMPTY findings as well — one fact, reported once."""
        plan = make_plan({})
        findings = [
            f for f in validate(plan, DINNER_ONLY, make_catalog(MAIN_A)) if f.day_index == 0
        ]
        assert [f.code for f in findings] == ["DAY_UNPLANNED"]

    def test_a_missing_slot_on_a_planned_day_is_reported(self, codes) -> None:  # type: ignore[no-untyped-def]
        profile = make_profile(budgets=(budget("dinner"), budget("lunch")))
        plan = make_plan({0: (make_entry("main_a"),)})
        findings = [
            f
            for f in validate(plan, profile, make_catalog(MAIN_A))
            if f.code == "SLOT_EMPTY" and f.day_index == 0
        ]
        assert [f.slot for f in findings] == ["lunch"]

    def test_neither_missing_code_is_ever_an_error(self) -> None:
        plan = make_plan({0: (make_entry("main_a"),)})
        profile = make_profile(budgets=(budget("dinner"), budget("lunch")))
        levels = {
            f.level
            for f in validate(plan, profile, make_catalog(MAIN_A))
            if f.code in {"SLOT_EMPTY", "DAY_UNPLANNED"}
        }
        assert levels == {"info"}

    def test_only_budgeted_slots_are_reported_as_missing(self, codes) -> None:  # type: ignore[no-untyped-def]
        """A profile that does not budget treats is not nagged about treats."""
        plan = make_plan({0: (make_entry("main_a"),)})
        findings = [
            f.slot
            for f in validate(plan, DINNER_ONLY, make_catalog(MAIN_A))
            if f.code == "SLOT_EMPTY"
        ]
        assert findings == []
