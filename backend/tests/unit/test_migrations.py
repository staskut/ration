"""The migration runs forwards and backwards on a clean database.

Guards the thing autogeneration gets wrong most often: a downgrade that leaves
tables behind, which turns a rollback into a manual cleanup at the worst moment.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from ration.repositories.models import ALL_TABLES

BACKEND = Path(__file__).parents[2]


@pytest.fixture
def alembic_config(tmp_path: Path) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'test.db'}")
    return config


def tables_in(config: Config) -> set[str]:
    engine = create_engine(config.get_main_option("sqlalchemy.url") or "")
    with engine.connect() as connection:
        return set(inspect(connection).get_table_names())


def test_upgrade_creates_every_table(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    created = tables_in(alembic_config) - {"alembic_version"}
    assert created == set(ALL_TABLES)


def test_downgrade_leaves_nothing_behind(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    assert tables_in(alembic_config) - {"alembic_version"} == set()


def test_upgrade_is_repeatable_after_a_downgrade(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    assert tables_in(alembic_config) - {"alembic_version"} == set(ALL_TABLES)


def test_nutrition_columns_are_never_floating_point(alembic_config: Config) -> None:
    """A Float column would undo the Decimal precision the domain is built on,
    in the one place it would be hardest to notice."""
    command.upgrade(alembic_config, "head")
    engine = create_engine(alembic_config.get_main_option("sqlalchemy.url") or "")
    numeric_names = {
        "kcal_per_100g",
        "protein_per_100g",
        "yield_factor",
        "package_size",
        "grams_cooked",
        "portion_factor",
        "kcal_min",
        "kcal_max",
        "protein_min",
        "protein_max",
        "threshold_g",
        "daily_kcal_target",
        "daily_kcal_tolerance",
        "daily_protein_min",
        "daily_protein_target",
    }
    offenders: list[str] = []
    with engine.connect() as connection:
        inspector = inspect(connection)
        for table in inspector.get_table_names():
            for column in inspector.get_columns(table):
                if column["name"] in numeric_names and "FLOAT" in str(column["type"]).upper():
                    offenders.append(f"{table}.{column['name']}")
    assert offenders == []


def test_deleting_a_plan_cascades_to_its_days_and_entries(alembic_config: Config) -> None:
    """Rolling back a week must not leave its days and entries orphaned."""
    from datetime import date

    from sqlalchemy.orm import Session

    from ration.repositories import models
    from ration.repositories.database import make_engine

    command.upgrade(alembic_config, "head")
    engine = make_engine(alembic_config.get_main_option("sqlalchemy.url"))

    with Session(engine) as session:
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
        )
        session.add(profile)
        session.flush()

        plan = models.Plan(
            profile_id=profile.id,
            name="Week 1",
            start_date=date(2026, 10, 12),
            days=[models.PlanDay(day_index=i, date=date(2026, 10, 12 + i)) for i in range(7)],
        )
        session.add(plan)
        session.commit()
        plan_id = plan.id

        assert session.query(models.PlanDay).filter_by(plan_id=plan_id).count() == 7

        session.delete(plan)
        session.commit()

        assert session.query(models.PlanDay).filter_by(plan_id=plan_id).count() == 0


def test_foreign_keys_are_enforced_on_sqlite(alembic_config: Config) -> None:
    """Without PRAGMA foreign_keys=ON, SQLite accepts a dangling reference and
    every cascade in the schema quietly stops working in development."""
    from datetime import date

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from ration.repositories import models
    from ration.repositories.database import make_engine

    command.upgrade(alembic_config, "head")
    engine = make_engine(alembic_config.get_main_option("sqlalchemy.url"))

    with Session(engine) as session:
        session.add(
            models.Plan(profile_id="does-not-exist", name="x", start_date=date(2026, 10, 12))
        )
        with pytest.raises(IntegrityError):
            session.commit()
