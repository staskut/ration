"""A real database for repository and API tests.

Unit tests never touch a database; these do. The split is deliberate — the
domain suite stays in milliseconds, and anything needing SQL lives here.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ration.repositories import models
from ration.repositories.database import make_engine

BACKEND = Path(__file__).parents[2]

# Everything in this package needs a database.
pytestmark = pytest.mark.integration


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """A migrated database.

    Built by running the real migrations rather than metadata.create_all, so the
    tests exercise the schema that will actually be deployed.
    """
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return make_engine(url)


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def small_catalog(session: Session) -> dict[str, str]:
    """Two ingredients and one module, with known values."""
    fish = models.Ingredient(
        slug="white_fish",
        kcal_per_100g=Decimal(130),
        protein_per_100g=Decimal(19),
        yield_factor=Decimal("0.72"),
        shop_section="meat_fish",
        names=[models.IngredientName(locale="ru", name="Белая рыба")],
        aliases=[models.IngredientAlias(locale="ru", alias="треска")],
    )
    pumpkin = models.Ingredient(
        slug="pumpkin",
        kcal_per_100g=Decimal(45),
        protein_per_100g=Decimal(1),
        yield_factor=Decimal("0.55"),
        shop_section="produce",
        names=[models.IngredientName(locale="ru", name="Тыква")],
    )
    session.add_all([fish, pumpkin])
    session.flush()

    module = models.Module(
        slug="dinner_fish_pumpkin",
        name="Рыба с тыквой",
        slot="dinner",
        role="main",
        batch_portions=1,
        lines=[
            models.ModuleLine(ingredient_id=fish.id, grams_cooked=Decimal(170), position=0),
            models.ModuleLine(
                ingredient_id=pumpkin.id,
                grams_cooked=Decimal(180),
                position=1,
                size_is_critical=True,
            ),
        ],
        tags=[models.ModuleTag(tag="fish"), models.ModuleTag(tag="home_only")],
    )
    session.add(module)
    session.commit()
    return {"fish": fish.id, "pumpkin": pumpkin.id, "module": module.id}


@pytest.fixture
def seeded_profile(session: Session, small_catalog: dict[str, str]) -> str:
    planner = models.User(
        email="planner@example.test",
        password_hash="x",
        display_name="Planner",
        role="planner",
    )
    session.add(planner)
    session.flush()

    profile = models.Profile(
        name="Reference",
        planner_user_id=planner.id,
        daily_kcal_target=Decimal(1700),
        daily_kcal_tolerance=Decimal(50),
        daily_protein_min=Decimal(105),
        daily_protein_target=Decimal(110),
        slot_budgets=[
            models.SlotBudget(
                slot="dinner",
                kcal_min=Decimal(470),
                kcal_max=Decimal(495),
                protein_min=Decimal(35),
                protein_max=Decimal(42),
            ),
            models.SlotBudget(
                slot="treat",
                kcal_min=Decimal(100),
                kcal_max=Decimal(150),
                protein_min=Decimal(0),
                protein_max=Decimal(5),
                optional=True,
            ),
        ],
        ingredient_rules=[
            models.ProfileIngredientRule(
                ingredient_id=small_catalog["pumpkin"],
                rule="caution",
                threshold_g=Decimal(200),
            )
        ],
        frequency_rules=[
            models.FrequencyRule(tag="treat", max_per_week=3),
            models.FrequencyRule(
                tag="alcohol", max_per_week=1, blocked_on_templates="duty_24h,training"
            ),
        ],
    )
    session.add(profile)
    session.commit()
    return profile.id


@pytest.fixture
def seeded_plan(session: Session, seeded_profile: str, small_catalog: dict[str, str]) -> str:
    plan = models.Plan(
        profile_id=seeded_profile,
        name="Неделя 1",
        start_date=date(2026, 10, 12),
        status="active",
        days=[
            models.PlanDay(
                day_index=index,
                date=date(2026, 10, 12 + index),
                day_template="training" if index == 0 else "normal",
                entries=(
                    [
                        models.PlanEntry(
                            slot="dinner",
                            module_id=small_catalog["module"],
                            portion_factor=Decimal("1.0"),
                            position=0,
                        )
                    ]
                    if index < 2
                    else []
                ),
            )
            for index in range(7)
        ],
    )
    session.add(plan)
    session.commit()
    return plan.id
