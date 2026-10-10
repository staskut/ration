"""Loading aggregates out of the database, and writing changes back.

Repositories know how to fetch efficiently and how to map. They contain no
business rules: no totals, no validation, no rounding. Those live in
`ration.domain` and are tested without a database.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ration.domain.types import Catalog, Feedback, Plan, Profile
from ration.repositories import mappers, models


class CatalogRepository:
    """The ingredient and module library."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self) -> Catalog:
        """Whole catalog in two queries plus their eager loads.

        Modules and ingredients are small — a few hundred rows — and every
        engine needs the lot, so paging would only add round trips.
        """
        ingredients = list(
            self._session.scalars(
                select(models.Ingredient).options(
                    selectinload(models.Ingredient.names),
                    selectinload(models.Ingredient.aliases),
                )
            )
        )
        modules = list(
            self._session.scalars(
                select(models.Module)
                .where(models.Module.archived.is_(False))
                .options(
                    selectinload(models.Module.lines),
                    selectinload(models.Module.tags),
                )
            )
        )
        return mappers.catalog_from(ingredients, modules)

    def ingredient_ids_by_slug(self) -> dict[str, str]:
        rows = self._session.execute(select(models.Ingredient.slug, models.Ingredient.id)).all()
        return {slug: ingredient_id for slug, ingredient_id in rows}

    def module_ids_by_slug(self) -> dict[str, str]:
        rows = self._session.execute(select(models.Module.slug, models.Module.id)).all()
        return {slug: module_id for slug, module_id in rows}


class ProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, profile_id: str) -> Profile | None:
        row = self._session.scalars(
            select(models.Profile)
            .where(models.Profile.id == profile_id)
            .options(
                selectinload(models.Profile.slot_budgets),
                selectinload(models.Profile.ingredient_rules),
                selectinload(models.Profile.frequency_rules),
            )
        ).one_or_none()
        if row is None:
            return None
        slugs = CatalogRepository(self._session).ingredient_ids_by_slug()
        return mappers.profile_to_domain(row, {v: k for k, v in slugs.items()})


class PlanRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, plan_id: str) -> Plan | None:
        """A whole week in a bounded number of queries.

        Eager-loading days and entries matters: a lazy load here would fire one
        query per day and per entry, which is 30-odd round trips for one screen.
        """
        row = self._session.scalars(
            select(models.Plan)
            .where(models.Plan.id == plan_id)
            .options(selectinload(models.Plan.days).selectinload(models.PlanDay.entries))
        ).one_or_none()
        if row is None:
            return None
        module_slugs = {
            module_id: slug
            for slug, module_id in CatalogRepository(self._session).module_ids_by_slug().items()
        }
        return mappers.plan_to_domain(row, module_slugs)

    def load_by_slug(self, slug: str) -> Plan | None:
        plan_id = self._session.scalars(
            select(models.Plan.id).where(models.Plan.slug == slug)
        ).one_or_none()
        return None if plan_id is None else self.load(plan_id)

    def feedback_for(self, plan_id: str) -> dict[str, Feedback]:
        rows = self._session.scalars(
            select(models.Feedback)
            .join(models.PlanEntry)
            .join(models.PlanDay)
            .where(models.PlanDay.plan_id == plan_id)
        )
        return {row.plan_entry_id: mappers.feedback_to_domain(row) for row in rows}

    def checked_ingredients(self, plan_id: str) -> set[str]:
        """Slugs the follower has ticked off."""
        rows = self._session.execute(
            select(models.Ingredient.slug)
            .join(
                models.ShoppingCheckState,
                models.ShoppingCheckState.ingredient_id == models.Ingredient.id,
            )
            .where(
                models.ShoppingCheckState.plan_id == plan_id,
                models.ShoppingCheckState.checked.is_(True),
            )
        ).all()
        return {slug for (slug,) in rows}
