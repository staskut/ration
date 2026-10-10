"""Seeding is repeatable, complete, and round-trips back to the fixture."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ration.config import Settings
from ration.domain.validation import validate
from ration.repositories import models
from ration.repositories.repositories import (
    CatalogRepository,
    PlanRepository,
    ProfileRepository,
)
from ration.seed import load_reference
from ration.seed.command import ProductionSeedRefused, seed

pytestmark = pytest.mark.integration


def count(session: Session, model: type) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


class TestSeedingLoadsTheFixture:
    def test_row_counts_match_the_fixture(self, engine: Engine) -> None:
        reference = seed(engine)
        with Session(engine) as session:
            assert count(session, models.Ingredient) == len(reference.catalog.ingredients)
            assert count(session, models.Module) == len(reference.catalog.modules)
            assert count(session, models.PlanDay) == 7

    def test_it_loads_the_expected_shape(self, engine: Engine) -> None:
        seed(engine)
        with Session(engine) as session:
            assert count(session, models.Ingredient) == 40
            assert count(session, models.Module) == 19
            assert count(session, models.Plan) == 1

    def test_both_accounts_are_created_and_paired(self, engine: Engine) -> None:
        seed(engine)
        with Session(engine) as session:
            profile = session.scalars(select(models.Profile)).one()
            assert profile.planner_user_id
            assert profile.follower_user_id
            assert profile.planner_user_id != profile.follower_user_id

    def test_pilot_feedback_is_attached_to_the_entries_that_were_tried(
        self, engine: Engine
    ) -> None:
        seed(engine)
        with Session(engine) as session:
            ratings = session.scalars(select(models.Feedback.rating)).all()
        assert ratings, "no feedback was attached"
        assert set(ratings) == {"liked"}


class TestSeedingIsRepeatable:
    def test_running_twice_leaves_the_same_rows(self, engine: Engine) -> None:
        """It runs on every container start in development, so a second run
        must not produce a second copy of everything."""
        seed(engine)
        with Session(engine) as session:
            first = {
                model.__name__: count(session, model)
                for model in (models.Ingredient, models.Module, models.PlanDay, models.PlanEntry)
            }

        seed(engine)
        with Session(engine) as session:
            second = {
                model.__name__: count(session, model)
                for model in (models.Ingredient, models.Module, models.PlanDay, models.PlanEntry)
            }

        assert first == second

    def test_reset_clears_before_loading(self, engine: Engine) -> None:
        seed(engine)
        seed(engine, reset=True)
        with Session(engine) as session:
            assert count(session, models.Ingredient) == 40
            assert count(session, models.Plan) == 1


class TestTheSeededDatabaseReproducesTheFixture:
    def test_the_catalog_round_trips(self, engine: Engine) -> None:
        seed(engine)
        reference = load_reference()
        with Session(engine) as session:
            loaded = CatalogRepository(session).load()

        assert set(loaded.ingredients) == set(reference.catalog.ingredients)
        assert set(loaded.modules) == set(reference.catalog.modules)
        for slug, expected in reference.catalog.ingredients.items():
            actual = loaded.ingredient(slug)
            assert actual.kcal_per_100g == expected.kcal_per_100g
            assert actual.yield_factor == expected.yield_factor
            assert actual.package_size == expected.package_size

    def test_the_plan_round_trips(self, engine: Engine) -> None:
        seed(engine)
        reference = load_reference()
        with Session(engine) as session:
            plan = PlanRepository(session).load_by_slug(reference.plan.id)

        assert plan is not None
        assert len(plan.days) == 7
        assert [day.day_template for day in plan.days] == [
            day.day_template for day in reference.plan.days
        ]
        assert [entry.module_id for entry in plan.all_entries] == [
            entry.module_id for entry in reference.plan.all_entries
        ]

    def test_the_seeded_plan_validates_exactly_as_the_golden_test_says(
        self, engine: Engine
    ) -> None:
        """The strongest check available: the database round trip must not
        change a single finding."""
        seed(engine)
        reference = load_reference()
        with Session(engine) as session:
            plan = PlanRepository(session).load_by_slug(reference.plan.id)
            assert plan is not None
            profile = ProfileRepository(session).load(plan.profile_id)
            catalog = CatalogRepository(session).load()

        assert profile is not None
        findings = validate(plan, profile, catalog)
        assert [f.code for f in findings] == ["DAY_UNPLANNED"]
        assert findings[0].day_index == 6


class TestProductionIsRefused:
    def test_seeding_production_raises(self, engine: Engine, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        """The reference plan is demo data; a production database holds one real
        person's dietary information."""
        from ration import config

        monkeypatch.setattr(
            config,
            "settings",
            lambda: Settings(
                database_url="postgresql://x",
                environment="production",
                session_secret="not-used-by-this-test",
            ),
        )
        from ration.seed import command

        monkeypatch.setattr(command, "settings", config.settings)
        with pytest.raises(ProductionSeedRefused):
            seed(engine)
