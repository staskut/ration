"""The module library over HTTP.

Totals are computed on every read through `ration.domain.nutrition`, never
stored. That is what makes correcting an ingredient's nutrition correct every
module that uses it, with no migration and no recomputation pass.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ration.api.deps import CurrentUserDep, PlannerDep, SessionDep
from ration.api.errors import ErrorDetail, conflict, not_found, unprocessable
from ration.api.routers.ingredients import slugify
from ration.api.schemas.modules import (
    ModuleInput,
    ModuleLineIO,
    ModulePatch,
    ModuleResponse,
)
from ration.domain.nutrition import module_totals
from ration.domain.types import DAYS_PER_PLAN, MAX_YIELD_FACTOR
from ration.repositories import mappers, models
from ration.repositories.repositories import CatalogRepository

router = APIRouter(tags=["modules"])


def _load(session: SessionDep, module_id: str) -> models.Module:
    row = session.scalars(
        select(models.Module)
        .where(models.Module.slug == module_id)
        .options(selectinload(models.Module.lines), selectinload(models.Module.tags))
    ).one_or_none()
    if row is None:
        raise not_found("Module")
    return row


def _to_response(row: models.Module, session: SessionDep) -> ModuleResponse:
    catalog = CatalogRepository(session).load()
    slugs = {i: s for s, i in CatalogRepository(session).ingredient_ids_by_slug().items()}
    domain_module = mappers.module_to_domain(row, slugs)
    totals = module_totals(domain_module, catalog)
    return ModuleResponse(
        id=row.slug,
        name=row.name,
        slot=row.slot,  # type: ignore[arg-type]
        role=row.role,  # type: ignore[arg-type]
        batch_portions=row.batch_portions,
        prep_notes=row.prep_notes,
        tags=sorted(t.tag for t in row.tags),
        lines=[
            ModuleLineIO(
                ingredient_id=slugs[line.ingredient_id],
                grams_cooked=line.grams_cooked,
                size_is_critical=line.size_is_critical,
                yield_factor_override=line.yield_factor_override,
            )
            for line in row.lines
        ],
        kcal=totals.kcal,
        protein_g=totals.protein_g,
    )


def _validate(lines: list[ModuleLineIO], batch_portions: int | None) -> None:
    if not lines:
        raise unprocessable(
            "MODULE_HAS_NO_LINES",
            "A module needs at least one ingredient line",
            ErrorDetail(field="lines", code="empty"),
        )
    if batch_portions is not None and not 1 <= batch_portions <= DAYS_PER_PLAN:
        raise unprocessable(
            "BATCH_PORTIONS_OUT_OF_RANGE",
            f"batch_portions must be 1..{DAYS_PER_PLAN}",
            ErrorDetail(field="batch_portions", code="out_of_range"),
        )
    for index, line in enumerate(lines):
        if line.grams_cooked <= 0:
            raise unprocessable(
                "GRAMS_MUST_BE_POSITIVE",
                "grams_cooked must be positive",
                ErrorDetail(field=f"lines.{index}.grams_cooked", code="not_positive"),
            )
        override = line.yield_factor_override
        if override is not None and not Decimal(0) < override <= MAX_YIELD_FACTOR:
            raise unprocessable(
                "YIELD_FACTOR_OUT_OF_RANGE",
                f"yield_factor_override must be in (0, {MAX_YIELD_FACTOR}]",
                ErrorDetail(field=f"lines.{index}.yield_factor_override", code="out_of_range"),
            )


def _resolve_ingredients(session: SessionDep, lines: list[ModuleLineIO]) -> dict[str, str]:
    ids = CatalogRepository(session).ingredient_ids_by_slug()
    missing = sorted({line.ingredient_id for line in lines} - ids.keys())
    if missing:
        raise unprocessable(
            "UNKNOWN_INGREDIENT",
            f"Unknown ingredient(s): {', '.join(missing)}",
            ErrorDetail(field="lines", code="unknown_ingredient"),
        )
    return ids


def _line_rows(lines: list[ModuleLineIO], ids: dict[str, str]) -> list[models.ModuleLine]:
    """Position comes from the submitted order, which is what preserves it."""
    return [
        models.ModuleLine(
            ingredient_id=ids[line.ingredient_id],
            grams_cooked=line.grams_cooked,
            size_is_critical=line.size_is_critical,
            yield_factor_override=line.yield_factor_override,
            position=position,
        )
        for position, line in enumerate(lines)
    ]


def _replace(owner: object, attribute: str, items: list, session: SessionDep) -> None:  # type: ignore[no-untyped-def]
    """Flush the delete before the insert.

    Assigning the replacement directly makes SQLAlchemy emit the INSERTs first,
    and the unique (module_id, position) constraint fires on the second edit.
    The trap that broke re-seeding in #21.
    """
    setattr(owner, attribute, [])
    session.flush()
    setattr(owner, attribute, items)
    session.flush()


@router.get("/modules", operation_id="listModules")
def list_modules(
    session: SessionDep,
    _user: CurrentUserDep,
    slot: Annotated[str | None, Query()] = None,
    role: Annotated[str | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
) -> list[ModuleResponse]:
    statement = (
        select(models.Module)
        .where(models.Module.archived.is_(False))
        .options(selectinload(models.Module.lines), selectinload(models.Module.tags))
    )
    if slot:
        statement = statement.where(models.Module.slot == slot)
    if role:
        statement = statement.where(models.Module.role == role)
    if tag:
        statement = statement.where(
            models.Module.id.in_(
                select(models.ModuleTag.module_id).where(models.ModuleTag.tag == tag)
            )
        )
    rows = sorted(session.scalars(statement).unique().all(), key=lambda r: r.name)
    return [_to_response(row, session) for row in rows]


@router.post("/modules", status_code=201, operation_id="createModule")
def create_module(body: ModuleInput, session: SessionDep, _planner: PlannerDep) -> ModuleResponse:
    _validate(body.lines, body.batch_portions)
    ids = _resolve_ingredients(session, body.lines)

    slug = slugify(body.name)
    if session.scalars(select(models.Module).where(models.Module.slug == slug)).one_or_none():
        raise conflict("MODULE_EXISTS", f"A module named {slug} already exists")

    row = models.Module(
        slug=slug,
        name=body.name,
        slot=body.slot,
        role=body.role,
        batch_portions=body.batch_portions,
        prep_notes=body.prep_notes,
        lines=_line_rows(body.lines, ids),
        tags=[models.ModuleTag(tag=t) for t in dict.fromkeys(body.tags)],
    )
    session.add(row)
    session.flush()
    return _to_response(row, session)


@router.get("/modules/{module_id}", operation_id="getModule")
def get_module(module_id: str, session: SessionDep, _user: CurrentUserDep) -> ModuleResponse:
    return _to_response(_load(session, module_id), session)


@router.patch("/modules/{module_id}", operation_id="updateModule")
def update_module(
    module_id: str, body: ModulePatch, session: SessionDep, _planner: PlannerDep
) -> ModuleResponse:
    row = _load(session, module_id)
    if body.lines is not None or body.batch_portions is not None:
        _validate(
            body.lines
            if body.lines is not None
            else [
                ModuleLineIO(
                    ingredient_id="x",
                    grams_cooked=line.grams_cooked,
                    size_is_critical=line.size_is_critical,
                )
                for line in row.lines
            ],
            body.batch_portions if body.batch_portions is not None else row.batch_portions,
        )

    for field in ("name", "slot", "role", "batch_portions", "prep_notes"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)

    if body.lines is not None:
        ids = _resolve_ingredients(session, body.lines)
        _replace(row, "lines", _line_rows(body.lines, ids), session)
    if body.tags is not None:
        _replace(row, "tags", [models.ModuleTag(tag=t) for t in dict.fromkeys(body.tags)], session)

    session.flush()
    return _to_response(row, session)


@router.delete("/modules/{module_id}", status_code=204, operation_id="deleteModule")
def delete_module(module_id: str, session: SessionDep, _planner: PlannerDep) -> Response:
    row = _load(session, module_id)

    # Checked before deleting: the foreign key would raise on commit, after the
    # handler returned, and surface as a 500 naming nothing useful.
    plans = session.scalars(
        select(models.Plan.name)
        .join(models.PlanDay)
        .join(models.PlanEntry)
        .where(models.PlanEntry.module_id == row.id)
        .distinct()
    ).all()
    if plans:
        raise conflict(
            "MODULE_IN_USE",
            f"Still used by {len(plans)} plan(s): {', '.join(sorted(plans)[:3])}",
        )

    session.delete(row)
    session.flush()
    return Response(status_code=204)
