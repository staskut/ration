"""Repositories return domain types, efficiently, with no ORM leakage."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import event
from sqlalchemy.orm import Session

from ration.domain.nutrition import module_totals
from ration.domain.shopping import shopping_list
from ration.domain.types import Catalog, Plan, Profile
from ration.repositories.repositories import (
    CatalogRepository,
    PlanRepository,
    ProfileRepository,
)


def count_queries(session: Session):  # type: ignore[no-untyped-def]
    """Context manager counting SQL statements, to pin down N+1 regressions."""

    class Counter:
        total = 0

    counter = Counter()

    def _on_execute(*_args: object, **_kwargs: object) -> None:
        counter.total += 1

    event.listen(session.get_bind(), "before_cursor_execute", _on_execute)
    return counter, lambda: event.remove(session.get_bind(), "before_cursor_execute", _on_execute)


class TestCatalogRepository:
    def test_load_returns_a_domain_catalog(self, session: Session, small_catalog) -> None:  # type: ignore[no-untyped-def]
        catalog = CatalogRepository(session).load()
        assert isinstance(catalog, Catalog)
        assert set(catalog.ingredients) == {"white_fish", "pumpkin"}
        assert set(catalog.modules) == {"dinner_fish_pumpkin"}

    def test_ingredients_are_keyed_by_slug_not_database_id(
        self, session: Session, small_catalog
    ) -> None:  # type: ignore[no-untyped-def]
        """The domain refers to ingredients by slug and never sees a row id."""
        catalog = CatalogRepository(session).load()
        assert small_catalog["fish"] not in catalog.ingredients

    def test_every_number_arrives_as_a_decimal(self, session: Session, small_catalog) -> None:  # type: ignore[no-untyped-def]
        fish = CatalogRepository(session).load().ingredient("white_fish")
        assert isinstance(fish.kcal_per_100g, Decimal)
        assert isinstance(fish.yield_factor, Decimal)
        assert fish.yield_factor == Decimal("0.72")

    def test_names_and_tags_survive_the_round_trip(self, session: Session, small_catalog) -> None:  # type: ignore[no-untyped-def]
        catalog = CatalogRepository(session).load()
        assert catalog.ingredient("white_fish").name("ru") == "Белая рыба"
        assert catalog.module("dinner_fish_pumpkin").tags == frozenset({"fish", "home_only"})

    def test_a_critical_line_keeps_its_flag(self, session: Session, small_catalog) -> None:  # type: ignore[no-untyped-def]
        lines = CatalogRepository(session).load().module("dinner_fish_pumpkin").lines
        assert [line.size_is_critical for line in lines] == [False, True]

    def test_the_loaded_catalog_feeds_the_engines_directly(
        self, session: Session, small_catalog
    ) -> None:  # type: ignore[no-untyped-def]
        """The whole point of mapping at this edge: no adapter in between."""
        catalog = CatalogRepository(session).load()
        totals = module_totals(catalog.module("dinner_fish_pumpkin"), catalog)
        # 170 g at 130 kcal/100 g + 180 g at 45 kcal/100 g
        assert totals.kcal == Decimal("302.0")

    def test_loading_the_catalog_stays_a_handful_of_queries(
        self, session: Session, small_catalog
    ) -> None:  # type: ignore[no-untyped-def]
        counter, stop = count_queries(session)
        try:
            CatalogRepository(session).load()
        finally:
            stop()
        assert counter.total <= 8, f"catalog load issued {counter.total} queries"


class TestProfileRepository:
    def test_load_returns_a_domain_profile(self, session: Session, seeded_profile: str) -> None:
        profile = ProfileRepository(session).load(seeded_profile)
        assert isinstance(profile, Profile)
        assert profile.daily_kcal_target == Decimal(1700)

    def test_budgets_rules_and_optionality_survive(
        self, session: Session, seeded_profile: str
    ) -> None:
        profile = ProfileRepository(session).load(seeded_profile)
        assert profile is not None
        dinner = profile.budget_for("dinner")
        treat = profile.budget_for("treat")
        assert dinner is not None and dinner.kcal_max == Decimal(495)
        assert treat is not None and treat.optional is True

    def test_ingredient_rules_use_slugs(self, session: Session, seeded_profile: str) -> None:
        profile = ProfileRepository(session).load(seeded_profile)
        assert profile is not None
        assert profile.rule_for("pumpkin") is not None

    def test_blocked_templates_round_trip_through_the_comma_list(
        self, session: Session, seeded_profile: str
    ) -> None:
        profile = ProfileRepository(session).load(seeded_profile)
        assert profile is not None
        alcohol = next(r for r in profile.frequency_rules if r.tag == "alcohol")
        assert alcohol.blocked_on_templates == frozenset({"training", "duty_24h"})

    def test_an_unknown_profile_is_none_rather_than_an_error(self, session: Session) -> None:
        assert ProfileRepository(session).load("nope") is None


class TestPlanRepository:
    def test_load_returns_a_seven_day_domain_plan(self, session: Session, seeded_plan: str) -> None:
        plan = PlanRepository(session).load(seeded_plan)
        assert isinstance(plan, Plan)
        assert len(plan.days) == 7
        assert sum(1 for day in plan.days if day.is_planned) == 2

    def test_entries_reference_modules_by_slug(self, session: Session, seeded_plan: str) -> None:
        plan = PlanRepository(session).load(seeded_plan)
        assert plan is not None
        assert plan.all_entries[0].module_id == "dinner_fish_pumpkin"

    def test_day_templates_survive(self, session: Session, seeded_plan: str) -> None:
        plan = PlanRepository(session).load(seeded_plan)
        assert plan is not None
        assert plan.days[0].day_template == "training"

    def test_loading_a_week_does_not_issue_a_query_per_entry(
        self, session: Session, seeded_plan: str
    ) -> None:
        """A lazy load here would be one query per day and per entry — about
        thirty round trips for a single screen."""
        session.expunge_all()
        counter, stop = count_queries(session)
        try:
            plan = PlanRepository(session).load(seeded_plan)
            assert plan is not None
            _ = [entry.module_id for day in plan.days for entry in day.entries]
        finally:
            stop()
        assert counter.total <= 8, f"plan load issued {counter.total} queries"

    def test_the_loaded_plan_feeds_the_shopping_engine(
        self, session: Session, seeded_plan: str
    ) -> None:
        plan = PlanRepository(session).load(seeded_plan)
        catalog = CatalogRepository(session).load()
        assert plan is not None
        lines = shopping_list(plan, catalog)
        fish = next(line for line in lines if line.ingredient_id == "white_fish")
        # Two dinners at 170 g cooked, divided by a 0.72 yield.
        assert fish.needed_raw_g == Decimal("472.2")

    def test_an_unknown_plan_is_none(self, session: Session) -> None:
        assert PlanRepository(session).load("nope") is None

    def test_check_state_starts_empty(self, session: Session, seeded_plan: str) -> None:
        assert PlanRepository(session).checked_ingredients(seeded_plan) == set()


class TestNumericPrecision:
    """SQLite has no decimal type and stores Numeric columns as REAL.

    Values therefore make a float round trip in development that they do not
    make in Postgres. The mapper converts back via str(), which is exact for the
    short decimals this catalog uses — but it is worth pinning, because a silent
    loss here would show up as a shopping list that is off by a gram.
    """

    def test_yield_factors_survive_the_float_round_trip(
        self, session: Session, small_catalog
    ) -> None:  # type: ignore[no-untyped-def]
        catalog = CatalogRepository(session).load()
        assert catalog.ingredient("white_fish").yield_factor == Decimal("0.72")
        assert catalog.ingredient("pumpkin").yield_factor == Decimal("0.55")

    def test_derived_quantities_stay_exact(self, session: Session, seeded_plan: str) -> None:
        plan = PlanRepository(session).load(seeded_plan)
        catalog = CatalogRepository(session).load()
        assert plan is not None
        lines = shopping_list(plan, catalog)
        pumpkin = next(line for line in lines if line.ingredient_id == "pumpkin")
        # 2 x 180 g cooked / 0.55 = 654.5454..., rounded to one decimal.
        assert pumpkin.needed_raw_g == Decimal("654.5")
