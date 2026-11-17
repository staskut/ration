"""Load the reference fixture into a database.

Idempotent and keyed on the fixture slugs, so running it twice leaves the same
rows rather than a second copy of everything. That matters because it runs on
every container start in development and compose.

Never runs in production. The reference plan is demo data, and a production
database holds one real person's dietary information.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from ration.config import FOLLOWER_EMAIL, PLANNER_EMAIL, settings
from ration.domain.types import Template
from ration.repositories import models
from ration.repositories.database import make_engine
from ration.seed.loader import ReferenceData, load_reference


def demo_start_date(today: date | None = None) -> date:
    """The Monday of the week the seed is running in.

    The fixture pins the reference week to 2026-10-12 because
    `docs/sample-plan-6-days.md` is the oracle for three golden tests and its
    dates are part of what they check. The *seeded* plan is a demo, and a demo
    whose follower screen shows a week that ended a month ago is broken — which
    is exactly what happened: the plan's week passed on 18 October 2026, the
    follower's Today screen became an error state with no way out, and nothing
    noticed until CI next ran four weeks later (#75).

    Monday, not today, because `day_index` 0 is Monday in the fixture and the
    templates hang off the weekday: training falls on days 0 and 3, the long
    shift on day 2. Shifting by anything but whole weeks would silently change
    what the demo demonstrates.
    """
    today = today or date.today()
    return today - timedelta(days=today.weekday())


# Re-exported: these moved to `ration.config` so the API can recognise a demo
# account without importing the seeder. Tests and scripts import them from here.
__all__ = ["FOLLOWER_EMAIL", "PLANNER_EMAIL", "ReferenceData", "main", "seed"]

# The seeded accounts get a hash that cannot verify, so an unseeded or
# half-configured deployment has no working credentials by accident.
DEV_PASSWORD_HASH_PLACEHOLDER = "!seed-set-a-password!"

# Set RATION_DEV_PASSWORD to give the seeded accounts a usable password, for
# local work and the end-to-end suite. It is ignored unless the seed is
# running at all, and the seed refuses to run in production — so this cannot
# put a known password on a real deployment.
DEV_PASSWORD_ENV = "RATION_DEV_PASSWORD"


class ProductionSeedRefused(RuntimeError):
    """Raised rather than writing demo data into a real person's database."""


def seed(engine: Engine, *, reset: bool = False, today: date | None = None) -> ReferenceData:
    """Load the reference fixture. `today` picks the week the plan lands in.

    The clock is injectable so a test can seed as if it were a fortnight ago
    and read the result now — which is the only way to check what happens to
    this demo *after* the seed, and precisely the case that went unnoticed for
    a month (#75). Production passes nothing and gets the current week.

    Safe to call repeatedly.
    """
    if settings().is_production:
        raise ProductionSeedRefused(
            "Refusing to seed a production database: the reference plan is demo data."
        )

    reference = load_reference()

    with Session(engine) as session:
        if reset:
            _clear(session)

        ingredient_ids = _upsert_ingredients(session, reference)
        module_ids = _upsert_modules(session, reference, ingredient_ids)
        profile_id, follower_id = _upsert_identity_and_profile(session, reference, ingredient_ids)
        _upsert_plan(session, reference, profile_id, module_ids, today)
        session.commit()

    assert follower_id  # the pairing is what makes the follower's screens work
    return reference


def _clear(session: Session) -> None:
    """Delete in dependency order. Cascades do the rest."""
    for model in (
        models.ShoppingCheckState,
        models.Feedback,
        models.PlanEntry,
        models.PlanDay,
        models.Plan,
        models.FrequencyRule,
        models.ProfileIngredientRule,
        models.SlotBudget,
        models.Profile,
        models.ModuleTag,
        models.ModuleLine,
        models.Module,
        models.IngredientAlias,
        models.IngredientName,
        models.Ingredient,
        models.User,
    ):
        session.execute(delete(model))
    session.flush()


def _replace(owner: object, attribute: str, new_items: list, session: Session) -> None:
    """Swap a collection out, flushing the delete before the insert.

    SQLAlchemy would otherwise emit the INSERTs for the replacement before the
    DELETEs for the orphans, and a unique constraint on the old rows — such as
    (module_id, position) — fires on the second seed. Clearing and flushing
    first is what makes re-seeding idempotent rather than a crash.
    """
    setattr(owner, attribute, [])
    session.flush()
    setattr(owner, attribute, new_items)
    session.flush()


def _upsert_ingredients(session: Session, reference: ReferenceData) -> dict[str, str]:
    existing = {row.slug: row for row in session.scalars(select(models.Ingredient))}
    ids: dict[str, str] = {}

    for slug, ingredient in reference.catalog.ingredients.items():
        row = existing.get(slug)
        if row is None:
            row = models.Ingredient(slug=slug)
            session.add(row)

        row.kcal_per_100g = ingredient.kcal_per_100g
        row.protein_per_100g = ingredient.protein_per_100g
        row.yield_factor = ingredient.yield_factor
        row.package_size = ingredient.package_size
        row.package_unit = ingredient.package_unit
        row.shop_section = ingredient.shop_section
        row.is_staple = ingredient.is_staple
        row.yield_source = ingredient.yield_source

        session.flush()
        _replace(
            row,
            "names",
            [
                models.IngredientName(locale=locale, name=name)
                for locale, name in ingredient.names.items()
            ],
            session,
        )
        ids[slug] = row.id

    return ids


def _upsert_modules(
    session: Session, reference: ReferenceData, ingredient_ids: dict[str, str]
) -> dict[str, str]:
    existing = {row.slug: row for row in session.scalars(select(models.Module))}
    ids: dict[str, str] = {}

    for slug, module in reference.catalog.modules.items():
        row = existing.get(slug)
        if row is None:
            row = models.Module(slug=slug)
            session.add(row)

        row.name = module.name
        row.slot = module.slot
        row.role = module.role
        row.batch_portions = module.batch_portions
        row.prep_notes = module.prep_notes
        session.flush()
        _replace(
            row,
            "lines",
            [
                models.ModuleLine(
                    ingredient_id=ingredient_ids[line.ingredient_id],
                    grams_cooked=line.grams_cooked,
                    size_is_critical=line.size_is_critical,
                    yield_factor_override=line.yield_factor_override,
                    position=position,
                )
                for position, line in enumerate(module.lines)
            ],
            session,
        )
        _replace(row, "tags", [models.ModuleTag(tag=tag) for tag in sorted(module.tags)], session)
        ids[slug] = row.id

    return ids


def _upsert_identity_and_profile(
    session: Session, reference: ReferenceData, ingredient_ids: dict[str, str]
) -> tuple[str, str]:
    planner = _upsert_user(session, PLANNER_EMAIL, "Reference planner", "planner")
    follower = _upsert_user(session, FOLLOWER_EMAIL, "Reference follower", "follower")
    session.flush()

    # Keyed on the planner, not on the profile's name. A seed that finds the
    # profile by its display name stops finding it the moment that name is
    # edited, and silently creates a second profile beside the first — both
    # claiming the same planner, with `deps.py` picking between them by
    # whichever row comes back first. The planner's address is the stable
    # identity here, because `_upsert_user` keys on it too.
    profile = session.scalars(
        select(models.Profile).where(models.Profile.planner_user_id == planner.id)
    ).one_or_none()
    if profile is None:
        profile = models.Profile(name=reference.profile.name)
        session.add(profile)

    profile.planner_user_id = planner.id
    profile.follower_user_id = follower.id
    profile.locale = reference.profile.locale
    profile.daily_kcal_target = reference.profile.daily_kcal_target
    profile.daily_kcal_tolerance = reference.profile.daily_kcal_tolerance
    profile.daily_protein_min = reference.profile.daily_protein_min
    profile.daily_protein_target = reference.profile.daily_protein_target

    session.flush()
    _replace(
        profile,
        "slot_budgets",
        [
            models.SlotBudget(
                slot=budget.slot,
                kcal_min=budget.kcal_min,
                kcal_max=budget.kcal_max,
                protein_min=budget.protein_min,
                protein_max=budget.protein_max,
                optional=budget.optional,
            )
            for budget in reference.profile.slot_budgets
        ],
        session,
    )
    _replace(
        profile,
        "ingredient_rules",
        [
            models.ProfileIngredientRule(
                ingredient_id=ingredient_ids[rule.ingredient_id],
                rule=rule.rule,
                threshold_g=rule.threshold_g,
            )
            for rule in reference.profile.ingredient_rules
        ],
        session,
    )
    _replace(
        profile,
        "frequency_rules",
        [
            models.FrequencyRule(
                tag=rule.tag,
                max_per_week=rule.max_per_week,
                blocked_on_templates=_join(rule.blocked_on_templates),
            )
            for rule in reference.profile.frequency_rules
        ],
        session,
    )
    return profile.id, follower.id


def _dev_password_hash() -> str | None:
    """A usable password, only when one was asked for.

    Imported lazily: the seed is a domain-adjacent command and argon2 is an API
    concern, so paying for it on every seed would be the wrong coupling.
    """
    password = os.environ.get(DEV_PASSWORD_ENV)
    if not password:
        return None
    from ration.api.security import hash_password

    return hash_password(password)


def _upsert_user(session: Session, email: str, display_name: str, role: str) -> models.User:
    row = session.scalars(select(models.User).where(models.User.email == email)).one_or_none()
    dev_hash = _dev_password_hash()

    if row is None:
        row = models.User(
            email=email,
            display_name=display_name,
            role=role,
            password_hash=dev_hash or DEV_PASSWORD_HASH_PLACEHOLDER,
        )
        session.add(row)
    else:
        row.display_name = display_name
        row.role = role
        # Only ever overwrite a password when one was explicitly supplied.
        if dev_hash:
            row.password_hash = dev_hash
    return row


def _upsert_plan(
    session: Session,
    reference: ReferenceData,
    profile_id: str,
    module_ids: dict[str, str],
    today: date | None = None,
) -> str:
    row = session.scalars(
        select(models.Plan).where(models.Plan.slug == reference.plan.id)
    ).one_or_none()
    if row is None:
        row = models.Plan(slug=reference.plan.id)
        session.add(row)

    start = demo_start_date(today)
    row.profile_id = profile_id
    row.name = reference.plan.name
    row.start_date = start
    row.status = reference.plan.status

    # Replaced wholesale, so re-seeding cannot accumulate days or entries.
    session.flush()
    _replace(
        row,
        "days",
        [
            models.PlanDay(
                day_index=day.day_index,
                date=start + timedelta(days=day.day_index),
                day_template=day.day_template,
                notes=day.notes,
                entries=[
                    models.PlanEntry(
                        slot=entry.slot,
                        module_id=module_ids[entry.module_id],
                        portion_factor=entry.portion_factor,
                        position=position,
                    )
                    for position, entry in enumerate(day.entries)
                ],
            )
            for day in reference.plan.days
        ],
        session,
    )

    _attach_feedback(session, reference, row, module_ids)
    return row.id


def _attach_feedback(
    session: Session,
    reference: ReferenceData,
    plan: models.Plan,
    module_ids: dict[str, str],
) -> None:
    """The pilot reported per module, so the same verdict lands on every entry
    that uses it."""
    by_module_id = {
        module_ids[slug]: feedback
        for slug, feedback in reference.feedback_by_module.items()
        if slug in module_ids
    }
    for day in plan.days:
        for entry in day.entries:
            feedback = by_module_id.get(entry.module_id)
            if feedback is None or feedback.status != "tried":
                continue
            entry.feedback = models.Feedback(
                status=feedback.status,
                rating=feedback.rating,
                bloating=feedback.bloating,
                satiety=feedback.satiety,
                note=feedback.note,
            )
    session.flush()


def _join(templates: frozenset[Template]) -> str | None:
    return ",".join(sorted(templates)) or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load the reference plan into the database.")
    parser.add_argument("--reset", action="store_true", help="Delete existing rows before loading.")
    args = parser.parse_args(argv)

    try:
        reference = seed(make_engine(), reset=args.reset)
    except ProductionSeedRefused as error:
        print(str(error), file=sys.stderr)
        return 1

    print(
        f"Seeded {len(reference.catalog.ingredients)} ingredients, "
        f"{len(reference.catalog.modules)} modules, "
        f"and the plan '{reference.plan.name}'."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
