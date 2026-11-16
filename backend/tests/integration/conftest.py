"""A real database for repository and API tests.

Unit tests never touch a database; these do. The split is deliberate — the
domain suite stays in milliseconds, and anything needing SQL lives here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

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

    SQLite by default, for speed. Set RATION_TEST_DATABASE_URL to run the same
    suite against Postgres — which is what production uses, and the only way to
    catch a SQLite-ism before it ships. Each test gets its own schema there, so
    they stay independent without paying for a database per test.
    """
    configured = os.environ.get("RATION_TEST_DATABASE_URL")
    if configured:
        yield from _postgres_engine(configured)
        return

    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    yield make_engine(url)


def _postgres_engine(url: str) -> Iterator[Engine]:
    """One throwaway schema per test, so tests do not see each other's rows."""
    import uuid

    from sqlalchemy import text

    schema = f"t_{uuid.uuid4().hex[:12]}"
    admin = make_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    admin.dispose()

    scoped = f"{url}?options=-csearch_path%3D{schema}"
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    # Alembic's config is a ConfigParser, which reads % as interpolation, so
    # the percent-encoded search_path has to be escaped on the way in.
    config.set_main_option("sqlalchemy.url", scoped.replace("%", "%%"))
    command.upgrade(config, "head")

    engine = make_engine(scoped)
    try:
        yield engine
    finally:
        engine.dispose()
        admin = make_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


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


# --------------------------------------------------------------------- API ---

SEED_PASSWORD = "correct-horse-battery"


@pytest.fixture
def api(engine: Engine):  # type: ignore[no-untyped-def]
    """A TestClient over a migrated, seeded database.

    The seeded accounts get a real password here. The seed itself writes a
    placeholder hash that cannot verify, so an unseeded deployment has no
    usable credentials by accident.
    """
    from fastapi.testclient import TestClient

    from ration.api.app import create_app
    from ration.api.security import hash_password
    from ration.seed.command import seed

    seed(engine)
    with Session(engine) as session:
        for user in session.scalars(select(models.User)):
            user.password_hash = hash_password(SEED_PASSWORD)
        session.commit()

    app = create_app()
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def planner(api):  # type: ignore[no-untyped-def]
    from ration.seed.command import PLANNER_EMAIL

    response = api.post("/api/auth/login", json={"email": PLANNER_EMAIL, "password": SEED_PASSWORD})
    assert response.status_code == 204, response.text
    return api


@pytest.fixture
def follower(api, engine: Engine):  # type: ignore[no-untyped-def]
    """A second client, so one test can hold both roles at once.

    Depends on `api` because that is what seeds the database and gives the
    accounts a usable password.
    """
    from fastapi.testclient import TestClient

    from ration.api.app import create_app
    from ration.seed.command import FOLLOWER_EMAIL

    app = create_app()
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/login", json={"email": FOLLOWER_EMAIL, "password": SEED_PASSWORD}
        )
        assert response.status_code == 204, response.text
        yield client


@pytest.fixture
def seeded_day(engine: Engine):  # type: ignore[no-untyped-def]
    """The ISO date of day N of the seeded plan.

    Derived from the row the seed wrote, never computed the way the seed
    computes it — a test that repeats the production arithmetic agrees with
    itself whatever either of them does.

    These dates used to be literals (`2026-10-12`…`2026-10-18`). The seed now
    anchors the demo plan to the current week, because a fixed week quietly
    expires: on 19 October 2026 the follower's Today screen became an error
    state with no way out of it, and no test noticed for a month (#75).
    """

    def _date(day_index: int = 0) -> str:
        with Session(engine) as session:
            plan = session.scalars(
                select(models.Plan).where(models.Plan.slug == "reference_week_1")
            ).one()
            day = next(d for d in plan.days if d.day_index == day_index)
            return day.date.isoformat()

    return _date


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def anonymous(api):  # type: ignore[no-untyped-def]
    """A client that has never signed in.

    Distinct from `api`, which the `planner` fixture logs in on and returns —
    so a test depending on both would otherwise get an authenticated client
    under the name `api` and quietly prove nothing.
    """
    from fastapi.testclient import TestClient

    with TestClient(api.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def cookies_for(api):  # type: ignore[no-untyped-def]
    """Drive one client as either role.

    WebSocket tests need this. Each TestClient runs its own event loop and the
    app records the loop it started on, so two clients mean two loops and a
    broadcast fired on one never reaches a socket held by the other. Production
    has a single process and a single loop, so one client switching identity is
    the faithful arrangement rather than a convenience.

    Identity is set on the client rather than passed per request, because
    starlette is deprecating per-request cookies.
    """
    from ration.seed.command import FOLLOWER_EMAIL, PLANNER_EMAIL

    jars: dict[str, dict[str, str]] = {}
    for role, email in (("planner", PLANNER_EMAIL), ("follower", FOLLOWER_EMAIL)):
        response = api.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
        assert response.status_code == 204, response.text
        jars[role] = dict(response.cookies)
    api.cookies.clear()

    class Identity(dict):  # type: ignore[type-arg]
        def act_as(self, role: str) -> None:
            api.cookies.clear()
            api.cookies.update(jars[role])

    identity = Identity(jars)
    return identity
