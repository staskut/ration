"""The ingredient catalog over HTTP.

Validation here is structural only — is this a well-formed ingredient. Whether
an ingredient is *allowed* for a person is a profile rule and lives in
`ration.domain.validation`, which is why nothing in this module knows about
exclusions.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ration.api.deps import CurrentUserDep, PlannerDep, SessionDep
from ration.api.errors import ErrorDetail, conflict, not_found, unprocessable
from ration.api.schemas.ingredients import (
    IngredientInput,
    IngredientPatch,
    IngredientResponse,
)
from ration.domain.types import MAX_YIELD_FACTOR
from ration.repositories import models

router = APIRouter(tags=["ingredients"])

# Cyrillic transliteration for slugs. Keeps ids readable in logs and URLs
# without depending on a library for forty rows.
_TRANSLIT = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "e",
        "ж": "zh",
        "з": "z",
        "и": "i",
        "й": "i",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "h",
        "ц": "c",
        "ч": "ch",
        "ш": "sh",
        "щ": "sch",
        "ъ": "",
        "ы": "y",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
    }
)


def slugify(name: str) -> str:
    folded = unicodedata.normalize("NFKD", name.strip().lower()).translate(_TRANSLIT)
    slug = re.sub(r"[^a-z0-9]+", "_", folded).strip("_")
    return slug or "ingredient"


def to_response(row: models.Ingredient) -> IngredientResponse:
    return IngredientResponse(
        id=row.slug,
        names={n.locale: n.name for n in row.names},
        aliases=[a.alias for a in row.aliases],
        kcal_per_100g=row.kcal_per_100g,
        protein_per_100g=row.protein_per_100g,
        yield_factor=row.yield_factor,
        yield_source=row.yield_source,  # type: ignore[arg-type]
        package_size=row.package_size,
        package_unit=row.package_unit,  # type: ignore[arg-type]
        shop_section=row.shop_section,  # type: ignore[arg-type]
        is_staple=row.is_staple,
    )


def load(session: SessionDep, ingredient_id: str) -> models.Ingredient:
    row = session.scalars(
        select(models.Ingredient)
        .where(models.Ingredient.slug == ingredient_id)
        .options(
            selectinload(models.Ingredient.names),
            selectinload(models.Ingredient.aliases),
        )
    ).one_or_none()
    if row is None:
        raise not_found("Ingredient")
    return row


def check_aliases(session: SessionDep, aliases: list[str], owner_id: str | None = None) -> None:
    """Refuse an alias another ingredient already answers to.

    `UNIQUE (locale, alias)` is correct — two ingredients answering to "cod"
    would make alias search ambiguous, which is the opposite of what aliases are
    for. But the constraint fires on flush, after the handler has returned, and
    escapes as a 500 that tells the planner nothing. Checking here turns it into
    a 409 naming the ingredient already holding it.

    The same treatment the delete path already gave foreign keys; this is the
    unique constraint sitting next to them.
    """
    if not aliases:
        return

    duplicates_in_request = {a for a in aliases if aliases.count(a) > 1}
    if duplicates_in_request:
        raise unprocessable(
            "DUPLICATE_ALIAS",
            f"Repeated alias in the request: {', '.join(sorted(duplicates_in_request))}",
            ErrorDetail(field="aliases", code="duplicate"),
        )

    taken = session.execute(
        select(models.IngredientAlias.alias, models.Ingredient.slug)
        .join(models.Ingredient)
        .where(models.IngredientAlias.alias.in_(aliases))
    ).all()
    clashes = [(alias, slug) for alias, slug in taken if slug != owner_id]
    if clashes:
        held = ", ".join(f"{alias!r} by {slug}" for alias, slug in sorted(clashes))
        raise conflict("ALIAS_IN_USE", f"Alias already in use: {held}")


def check_yield(factor: object, source: str | None) -> None:
    """Reject what the domain type would reject, but as a 422 rather than a 500.

    Duplicating the bound is deliberate: the domain raises ValueError, which is
    the right behaviour for a pure layer but the wrong status code for a client.
    """
    from decimal import Decimal

    if factor is None:
        return
    value = Decimal(str(factor))
    if not Decimal(0) < value <= MAX_YIELD_FACTOR:
        raise unprocessable(
            "YIELD_FACTOR_OUT_OF_RANGE",
            f"yield_factor must be in (0, {MAX_YIELD_FACTOR}]",
            ErrorDetail(field="yield_factor", code="out_of_range"),
        )
    if value == Decimal(1) and source == "estimated":
        raise unprocessable(
            "YIELD_SOURCE_INCONSISTENT",
            "A yield of 1.0 is as_purchased, not estimated",
            ErrorDetail(field="yield_source", code="inconsistent"),
        )


@router.get("/ingredients", operation_id="listIngredients")
def list_ingredients(
    session: SessionDep,
    _user: CurrentUserDep,
    q: Annotated[str | None, Query()] = None,
    locale: Annotated[str, Query()] = "ru",
    section: Annotated[str | None, Query()] = None,
) -> list[IngredientResponse]:
    """Search the catalog. Both roles may read it.

    A follower needs this: Today and the shopping list both render ingredient
    names, so a follower who cannot read the catalog cannot use either screen.
    """
    statement = select(models.Ingredient).options(
        selectinload(models.Ingredient.names),
        selectinload(models.Ingredient.aliases),
    )
    if section:
        statement = statement.where(models.Ingredient.shop_section == section)

    rows = list(session.scalars(statement).unique().all())

    if q:
        # Filtered in Python rather than in SQL, deliberately. SQLite's lower()
        # is ASCII-only and leaves Cyrillic untouched, so `WHERE lower(name)
        # LIKE ...` matches Russian text in Postgres and silently matches
        # nothing in development. A search that works in production and fails
        # on your machine is worse than either behaviour.
        #
        # The catalog is a curated hundred-odd rows (PRD §3.1), so one query and
        # a pass over the result is cheaper than the divergence.
        needle = q.casefold()
        rows = [
            row
            for row in rows
            if any(needle in n.name.casefold() for n in row.names)
            or any(needle in a.alias.casefold() for a in row.aliases)
        ]

    rows.sort(key=lambda r: _display(r, locale))
    return [to_response(row) for row in rows]


def _display(row: models.Ingredient, locale: str) -> str:
    by_locale = {n.locale: n.name for n in row.names}
    return by_locale.get(locale) or next(iter(by_locale.values()), row.slug)


@router.post("/ingredients", status_code=201, operation_id="createIngredient")
def create_ingredient(
    body: IngredientInput, session: SessionDep, _planner: PlannerDep
) -> IngredientResponse:
    if "ru" not in body.names or not body.names["ru"].strip():
        raise unprocessable(
            "NAME_REQUIRED",
            "A Russian name is required",
            ErrorDetail(field="names.ru", code="missing"),
        )
    check_yield(body.yield_factor, body.yield_source)
    check_aliases(session, body.aliases)

    slug = slugify(body.names["ru"])
    if session.scalars(
        select(models.Ingredient).where(models.Ingredient.slug == slug)
    ).one_or_none():
        raise conflict("INGREDIENT_EXISTS", f"An ingredient named {slug} already exists")

    row = models.Ingredient(
        slug=slug,
        kcal_per_100g=body.kcal_per_100g,
        protein_per_100g=body.protein_per_100g,
        yield_factor=body.yield_factor,
        yield_source=body.yield_source,
        package_size=body.package_size,
        package_unit=body.package_unit,
        shop_section=body.shop_section,
        is_staple=body.is_staple,
        names=[models.IngredientName(locale=k, name=v) for k, v in body.names.items()],
        aliases=[models.IngredientAlias(locale="ru", alias=a) for a in body.aliases],
    )
    session.add(row)
    session.flush()
    return to_response(row)


@router.get("/ingredients/{ingredient_id}", operation_id="getIngredient")
def get_ingredient(
    ingredient_id: str, session: SessionDep, _user: CurrentUserDep
) -> IngredientResponse:
    return to_response(load(session, ingredient_id))


@router.patch("/ingredients/{ingredient_id}", operation_id="updateIngredient")
def update_ingredient(
    ingredient_id: str,
    body: IngredientPatch,
    session: SessionDep,
    _planner: PlannerDep,
) -> IngredientResponse:
    row = load(session, ingredient_id)
    check_yield(
        body.yield_factor if body.yield_factor is not None else row.yield_factor,
        body.yield_source if body.yield_source is not None else row.yield_source,
    )

    for field in (
        "kcal_per_100g",
        "protein_per_100g",
        "yield_factor",
        "yield_source",
        "package_size",
        "package_unit",
        "shop_section",
        "is_staple",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)

    # The slug is not derived again. Renaming an ingredient must not change its
    # id, or every module line referencing it would be orphaned.
    if body.names is not None:
        _replace(
            row,
            "names",
            [models.IngredientName(locale=k, name=v) for k, v in body.names.items()],
            session,
        )
    if body.aliases is not None:
        check_aliases(session, body.aliases, owner_id=row.slug)
        _replace(
            row,
            "aliases",
            [models.IngredientAlias(locale="ru", alias=a) for a in body.aliases],
            session,
        )

    session.flush()
    return to_response(row)


@router.delete("/ingredients/{ingredient_id}", status_code=204, operation_id="deleteIngredient")
def delete_ingredient(ingredient_id: str, session: SessionDep, _planner: PlannerDep) -> Response:
    row = load(session, ingredient_id)

    # Checked before deleting rather than caught afterwards: the foreign key
    # would raise on commit, long after the handler returned, and surface as a
    # 500 instead of telling the planner which module is in the way.
    users = session.scalars(
        select(models.Module.slug)
        .join(models.ModuleLine)
        .where(models.ModuleLine.ingredient_id == row.id)
        .distinct()
    ).all()
    if users:
        raise conflict(
            "INGREDIENT_IN_USE",
            f"Still used by {len(users)} module(s): {', '.join(sorted(users)[:5])}",
        )

    session.delete(row)
    session.flush()
    return Response(status_code=204)


def _replace(owner: object, attribute: str, items: list, session) -> None:  # type: ignore[no-untyped-def]
    """Flush the delete before the insert, or a unique constraint fires.

    The same ordering trap that broke re-seeding in #21.
    """
    setattr(owner, attribute, [])
    session.flush()
    setattr(owner, attribute, items)
    session.flush()
