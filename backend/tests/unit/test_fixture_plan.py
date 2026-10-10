"""Profile, plan and feedback load into domain types and match the document."""

from datetime import date
from decimal import Decimal

from ration.domain.nutrition import day_totals, totals_by_slot
from ration.seed.loader import load_reference

REFERENCE = load_reference()


class TestProfile:
    def test_targets_match_sections_1_and_5(self) -> None:
        profile = REFERENCE.profile
        assert profile.daily_kcal_target == Decimal(1700)
        assert profile.daily_kcal_tolerance == Decimal(50)
        assert profile.daily_protein_min == Decimal(105)
        assert profile.daily_protein_target == Decimal(110)

    def test_every_slot_has_a_budget(self) -> None:
        slots = {b.slot for b in REFERENCE.profile.slot_budgets}
        assert slots == {"breakfast", "lunch", "snack", "dinner", "treat"}

    def test_frequency_rules_are_data_rather_than_code(self) -> None:
        rules = {r.tag: r for r in REFERENCE.profile.frequency_rules}
        assert rules["liver"].max_per_week == 1
        assert rules["salted_fish"].max_per_week == 2
        assert rules["treat"].max_per_week == 3

    def test_alcohol_is_blocked_on_training_and_duty_days(self) -> None:
        """Section 7: wine only on a day with no duty, driving or training."""
        alcohol = next(r for r in REFERENCE.profile.frequency_rules if r.tag == "alcohol")
        assert alcohol.blocked_on_templates == frozenset({"training", "duty_24h"})


class TestPlan:
    def test_a_plan_is_seven_days_with_six_planned(self) -> None:
        """The pilot ran six days; the seventh is deliberately left unplanned so
        the fixture exercises the partial-week case too."""
        assert len(REFERENCE.plan.days) == 7
        assert sum(1 for day in REFERENCE.plan.days if day.is_planned) == 6
        assert not REFERENCE.plan.days[6].is_planned

    def test_day_templates_match_section_8(self) -> None:
        templates = [day.day_template for day in REFERENCE.plan.days]
        assert templates[0] == "training"
        assert templates[2] == "long_shift"
        assert templates[3] == "training"
        assert templates[1] == templates[4] == templates[5] == "normal"

    def test_dates_run_consecutively_from_the_start(self) -> None:
        assert REFERENCE.plan.start_date == date(2026, 10, 12)
        assert [day.date.day for day in REFERENCE.plan.days] == list(range(12, 19))

    def test_each_batch_lunch_runs_three_consecutive_days(self) -> None:
        """Section 10 cooks one lunch for days 1-3 and the other for days 4-6."""
        by_day = [
            next((e.module_id for e in day.entries if e.slot == "lunch"), None)
            for day in REFERENCE.plan.days
        ]
        assert by_day[:3] == ["lunch_rice_noodles_turkey"] * 3
        assert by_day[3:6] == ["lunch_roll_chicken"] * 3

    def test_wine_is_planned_only_on_a_day_its_rule_allows(self) -> None:
        wine_days = [
            day.day_template
            for day in REFERENCE.plan.days
            if any(e.module_id == "treat_wine" for e in day.entries)
        ]
        assert wine_days == ["normal"]

    def test_three_treats_in_the_week(self) -> None:
        treats = [e for e in REFERENCE.plan.all_entries if e.slot == "treat"]
        assert len(treats) == 3

    def test_entry_ids_are_unique(self) -> None:
        ids = [e.id for e in REFERENCE.plan.all_entries]
        assert len(ids) == len(set(ids))


class TestPlannedNutrition:
    def test_every_planned_day_hits_the_calorie_target(self) -> None:
        profile = REFERENCE.profile
        low = profile.daily_kcal_target - profile.daily_kcal_tolerance
        high = profile.daily_kcal_target + profile.daily_kcal_tolerance
        for day in REFERENCE.plan.days:
            if not day.is_planned:
                continue
            kcal = day_totals(day, REFERENCE.catalog).kcal
            assert low <= kcal <= high, f"day {day.day_index}: {kcal:.0f} kcal"

    def test_every_planned_day_clears_the_protein_minimum(self) -> None:
        for day in REFERENCE.plan.days:
            if not day.is_planned:
                continue
            protein = day_totals(day, REFERENCE.catalog).protein_g
            assert protein >= REFERENCE.profile.daily_protein_min

    def test_every_slot_sits_inside_its_budget(self) -> None:
        """A slot's total, not an individual entry — the sum is what budgets
        apply to once a slot can hold a main and sides."""
        breaches = []
        for day in REFERENCE.plan.days:
            for slot, totals in totals_by_slot(day, REFERENCE.catalog).items():
                budget = REFERENCE.profile.budget_for(slot)
                assert budget is not None
                if not budget.kcal_min <= totals.kcal <= budget.kcal_max:
                    breaches.append(f"day {day.day_index} {slot}: {totals.kcal:.0f} kcal")
                if not budget.protein_min <= totals.protein_g <= budget.protein_max:
                    breaches.append(f"day {day.day_index} {slot}: {totals.protein_g:.1f} g")
        assert breaches == []

    def test_an_unplanned_day_is_zero_rather_than_a_breach(self) -> None:
        assert day_totals(REFERENCE.plan.days[6], REFERENCE.catalog).kcal == Decimal(0)


class TestFeedback:
    def test_the_split_matches_section_14(self) -> None:
        statuses = [f.status for f in REFERENCE.feedback_by_module.values()]
        assert statuses.count("tried") == 7
        assert statuses.count("not_tried") == 9

    def test_untried_modules_carry_no_rating(self) -> None:
        """`not_tried` is a state, not missing data: an unexplored module must
        not be mistaken for a rejected one."""
        for feedback in REFERENCE.feedback_by_module.values():
            if feedback.status == "not_tried":
                assert feedback.rating is None

    def test_everything_tried_was_liked(self) -> None:
        tried = [f for f in REFERENCE.feedback_by_module.values() if f.status == "tried"]
        assert {f.rating for f in tried} == {"liked"}

    def test_bloating_and_satiety_went_unreported_all_week(self) -> None:
        """The finding that reshaped the model: the planner's two chosen scales
        got no signal at all, while tried/liked got it for every module."""
        assert all(f.bloating is None for f in REFERENCE.feedback_by_module.values())
        assert all(f.satiety is None for f in REFERENCE.feedback_by_module.values())

    def test_every_rated_module_exists_in_the_catalog(self) -> None:
        unknown = set(REFERENCE.feedback_by_module) - set(REFERENCE.catalog.modules)
        assert unknown == set()

    def test_the_roll_records_why_it_was_awkward(self) -> None:
        note = REFERENCE.feedback_by_module["lunch_roll_chicken"].note or ""
        assert "45" in note and "75" in note
