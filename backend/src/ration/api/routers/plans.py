"""Plans, days and entries.

Every mutation returns a fresh validation report beside the thing it changed.
Validation is cheap — one plan, in memory — and a planner should never be
looking at a changed plan next to a stale report.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from fastapi import APIRouter, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ration.api.deps import CurrentUserDep, OwnedPlanDep, PlannerDep, SessionDep
from ration.api.errors import ErrorDetail, conflict, not_found, unprocessable
from ration.api.schemas.plans import (
    FindingIO,
    PlanCreate,
    PlanDayPut,
    PlanDayResponse,
    PlanDayWithValidation,
    PlanEntryCreate,
    PlanEntryPatch,
    PlanEntryResponse,
    PlanEntryWithValidation,
    PlanPatch,
    PlanResponse,
    PlanSummary,
    SlotTotals,
    ValidationReport,
)
from ration.domain.nutrition import day_totals, entry_totals, totals_by_slot
from ration.domain.types import DAYS_PER_PLAN, Catalog
from ration.domain.validation import validate
from ration.repositories import mappers, models
from ration.repositories.repositories import (
    CatalogRepository,
    PlanRepository,
    ProfileRepository,
)

router = APIRouter(tags=["plans"])

MIN_PORTION = Decimal("0.5")
MAX_PORTION = Decimal("1.5")


def _plan_row(session: SessionDep, plan_id: str) -> models.Plan:
    return session.scalars(
        select(models.Plan)
        .where(models.Plan.id == plan_id)
        .options(selectinload(models.Plan.days).selectinload(models.PlanDay.entries))
    ).one()


def _context(session: SessionDep, plan_id: str):  # type: ignore[no-untyped-def]
    """The domain objects every response needs."""
    catalog = CatalogRepository(session).load()
    plan = PlanRepository(session).load(plan_id)
    assert plan is not None
    profile = ProfileRepository(session).load(plan.profile_id)
    assert profile is not None
    return catalog, plan, profile


def _report(session: SessionDep, plan_id: str) -> ValidationReport:
    catalog, plan, profile = _context(session, plan_id)
    findings = validate(plan, profile, catalog)
    return ValidationReport(
        findings=[
            FindingIO(
                level=f.level,
                code=f.code,
                message_key=f.message_key,
                params=dict(f.params),
                day_index=f.day_index,
                slot=f.slot,
                entry_id=f.entry_id,
            )
            for f in findings
        ],
        error_count=sum(1 for f in findings if f.level == "error"),
        warning_count=sum(1 for f in findings if f.level == "warning"),
    )


def _entry_response(
    entry_row: models.PlanEntry, catalog: Catalog, module_slugs: dict[str, str]
) -> PlanEntryResponse:
    slug = module_slugs[entry_row.module_id]
    module = catalog.module(slug)
    domain_entry = mappers.plan_entry_to_domain(entry_row, module_slugs)
    totals = entry_totals(domain_entry, catalog)
    return PlanEntryResponse(
        id=entry_row.id,
        slot=entry_row.slot,  # type: ignore[arg-type]
        module_id=slug,
        module_name=module.name,
        role=module.role,
        portion_factor=entry_row.portion_factor,
        position=entry_row.position,
        kcal=totals.kcal,
        protein_g=totals.protein_g,
    )


def _day_response(
    day_row: models.PlanDay, catalog: Catalog, module_slugs: dict[str, str]
) -> PlanDayResponse:
    domain_day = mappers.plan_day_to_domain(day_row, module_slugs)
    totals = day_totals(domain_day, catalog)
    per_slot = totals_by_slot(domain_day, catalog)
    return PlanDayResponse(
        day_index=day_row.day_index,
        date=day_row.date,
        day_template=day_row.day_template,  # type: ignore[arg-type]
        notes=day_row.notes,
        entries=[
            _entry_response(e, catalog, module_slugs)
            for e in sorted(day_row.entries, key=lambda e: (e.slot, e.position))
        ],
        kcal=totals.kcal,
        protein_g=totals.protein_g,
        slot_totals=[
            SlotTotals(slot=slot, kcal=t.kcal, protein_g=t.protein_g)
            for slot, t in sorted(per_slot.items())
        ],
    )


def _plan_response(row: models.Plan, session: SessionDep) -> PlanResponse:
    catalog = CatalogRepository(session).load()
    slugs = {i: s for s, i in CatalogRepository(session).module_ids_by_slug().items()}
    return PlanResponse(
        id=row.id,
        name=row.name,
        profile_id=row.profile_id,
        start_date=row.start_date,
        status=row.status,  # type: ignore[arg-type]
        days=[
            _day_response(d, catalog, slugs) for d in sorted(row.days, key=lambda d: d.day_index)
        ],
    )


@router.get("/plans", operation_id="listPlans")
def list_plans(session: SessionDep, user: CurrentUserDep) -> list[PlanSummary]:
    rows = session.scalars(
        select(models.Plan)
        .where(models.Plan.profile_id == user.profile_id)
        .order_by(models.Plan.start_date.desc())
    ).all()
    return [
        PlanSummary(
            id=r.id,
            name=r.name,
            profile_id=r.profile_id,
            start_date=r.start_date,
            status=r.status,  # type: ignore[arg-type]
        )
        for r in rows
    ]


@router.post("/plans", status_code=201, operation_id="createPlan")
def create_plan(body: PlanCreate, session: SessionDep, planner: PlannerDep) -> PlanResponse:
    source: models.Plan | None = None
    if body.copy_from_plan_id:
        source = session.get(models.Plan, body.copy_from_plan_id)
        if source is None or source.profile_id != planner.profile_id:
            raise not_found("Plan")

    row = models.Plan(
        profile_id=planner.profile_id,
        name=body.name,
        start_date=body.start_date,
        status="draft",
    )
    # Seven days are created with the plan, in the same transaction. A six-day
    # plan must never be observable (PRD 3.6).
    row.days = [
        models.PlanDay(
            day_index=index,
            date=body.start_date + timedelta(days=index),
            day_template="normal",
        )
        for index in range(DAYS_PER_PLAN)
    ]
    session.add(row)
    session.flush()

    if source is not None:
        _copy_into(row, source, session)

    session.flush()
    return _plan_response(_plan_row(session, row.id), session)


def _copy_into(target: models.Plan, source: models.Plan, session: SessionDep) -> None:
    """Copy templates and entries. The copy is independent of the source."""
    by_index = {d.day_index: d for d in source.days}
    for day in target.days:
        origin = by_index.get(day.day_index)
        if origin is None:
            continue
        day.day_template = origin.day_template
        day.notes = origin.notes
        day.entries = [
            models.PlanEntry(
                slot=e.slot,
                module_id=e.module_id,
                portion_factor=e.portion_factor,
                position=e.position,
            )
            for e in origin.entries
        ]
    session.flush()


@router.get("/plans/{plan_id}", operation_id="getPlan")
def get_plan(plan: OwnedPlanDep, session: SessionDep) -> PlanResponse:
    return _plan_response(_plan_row(session, plan.id), session)


@router.patch("/plans/{plan_id}", operation_id="updatePlan")
def update_plan(
    plan: OwnedPlanDep, body: PlanPatch, session: SessionDep, _planner: PlannerDep
) -> PlanResponse:
    if body.name is not None:
        plan.name = body.name
    if body.status is not None:
        plan.status = body.status
    session.flush()
    return _plan_response(_plan_row(session, plan.id), session)


@router.delete("/plans/{plan_id}", status_code=204, operation_id="deletePlan")
def delete_plan(plan: OwnedPlanDep, session: SessionDep, _planner: PlannerDep) -> Response:
    session.delete(plan)
    session.flush()
    return Response(status_code=204)


def _day(session: SessionDep, plan: models.Plan, day_index: int) -> models.PlanDay:
    if not 0 <= day_index < DAYS_PER_PLAN:
        raise unprocessable(
            "DAY_INDEX_OUT_OF_RANGE",
            f"day_index must be 0..{DAYS_PER_PLAN - 1}",
            ErrorDetail(field="day_index", code="out_of_range"),
        )
    row = session.scalars(
        select(models.PlanDay).where(
            models.PlanDay.plan_id == plan.id, models.PlanDay.day_index == day_index
        )
    ).one_or_none()
    if row is None:
        raise not_found("Day")
    return row


@router.put("/plans/{plan_id}/days/{day_index}", operation_id="updatePlanDay")
def update_day(
    plan: OwnedPlanDep,
    day_index: int,
    body: PlanDayPut,
    session: SessionDep,
    _planner: PlannerDep,
) -> PlanDayWithValidation:
    row = _day(session, plan, day_index)
    if body.day_template is not None:
        row.day_template = body.day_template
    if body.notes is not None:
        row.notes = body.notes
    session.flush()

    catalog = CatalogRepository(session).load()
    slugs = {i: s for s, i in CatalogRepository(session).module_ids_by_slug().items()}
    return PlanDayWithValidation(
        day=_day_response(row, catalog, slugs),
        validation=_report(session, plan.id),
    )


# --------------------------------------------------------------------- entries


def _entry(session: SessionDep, plan: models.Plan, entry_id: str) -> models.PlanEntry:
    row = session.scalars(
        select(models.PlanEntry)
        .join(models.PlanDay)
        .where(models.PlanEntry.id == entry_id, models.PlanDay.plan_id == plan.id)
    ).one_or_none()
    if row is None:
        raise not_found("Entry")
    return row


def _check_portion(factor: Decimal | None) -> None:
    if factor is not None and not MIN_PORTION <= factor <= MAX_PORTION:
        raise unprocessable(
            "PORTION_FACTOR_OUT_OF_RANGE",
            f"portion_factor must be {MIN_PORTION}..{MAX_PORTION}",
            ErrorDetail(field="portion_factor", code="out_of_range"),
        )


def _module(session: SessionDep, module_id: str) -> models.Module:
    row = session.scalars(
        select(models.Module)
        .where(models.Module.slug == module_id)
        .options(selectinload(models.Module.lines), selectinload(models.Module.tags))
    ).one_or_none()
    if row is None:
        raise unprocessable(
            "UNKNOWN_MODULE",
            f"Unknown module: {module_id}",
            ErrorDetail(field="module_id", code="unknown"),
        )
    return row


def _check_slot_fits(module: models.Module, slot: str) -> None:
    if module.slot != slot:
        raise unprocessable(
            "MODULE_SLOT_MISMATCH",
            f"{module.slug} is a {module.slot} module, not {slot}",
            ErrorDetail(field="module_id", code="slot_mismatch"),
        )


def _check_single_main(
    session: SessionDep,
    day: models.PlanDay,
    slot: str,
    module: models.Module,
    excluding: str | None = None,
) -> None:
    """At most one `main` per slot.

    Enforced here rather than by a partial unique index, which SQLite cannot
    express portably (LLD §2). Any number of `side` entries is fine.
    """
    if module.role != "main":
        return
    existing = session.scalars(
        select(models.PlanEntry)
        .join(models.Module, models.Module.id == models.PlanEntry.module_id)
        .where(
            models.PlanEntry.plan_day_id == day.id,
            models.PlanEntry.slot == slot,
            models.Module.role == "main",
        )
    ).all()
    if any(e.id != excluding for e in existing):
        raise conflict(
            "SLOT_ALREADY_HAS_A_MAIN",
            f"{slot} already has a main entry on day {day.day_index}. "
            "Replace it, or add this module as a side.",
        )


def _next_position(session: SessionDep, day: models.PlanDay, slot: str) -> int:
    taken = session.scalars(
        select(models.PlanEntry.position).where(
            models.PlanEntry.plan_day_id == day.id, models.PlanEntry.slot == slot
        )
    ).all()
    return (max(taken) + 1) if taken else 0


def _entry_with_validation(
    row: models.PlanEntry, plan_id: str, session: SessionDep
) -> PlanEntryWithValidation:
    catalog = CatalogRepository(session).load()
    slugs = {i: s for s, i in CatalogRepository(session).module_ids_by_slug().items()}
    return PlanEntryWithValidation(
        entry=_entry_response(row, catalog, slugs),
        validation=_report(session, plan_id),
    )


@router.post(
    "/plans/{plan_id}/days/{day_index}/entries",
    status_code=201,
    operation_id="createPlanEntry",
)
def create_entry(
    plan: OwnedPlanDep,
    day_index: int,
    body: PlanEntryCreate,
    session: SessionDep,
    _planner: PlannerDep,
) -> PlanEntryWithValidation:
    day = _day(session, plan, day_index)
    _check_portion(body.portion_factor)
    module = _module(session, body.module_id)
    _check_slot_fits(module, body.slot)
    _check_single_main(session, day, body.slot, module)

    row = models.PlanEntry(
        plan_day_id=day.id,
        slot=body.slot,
        module_id=module.id,
        portion_factor=body.portion_factor or Decimal(1),
        position=(
            body.position if body.position is not None else _next_position(session, day, body.slot)
        ),
    )
    session.add(row)
    session.flush()
    return _entry_with_validation(row, plan.id, session)


@router.patch("/plans/{plan_id}/entries/{entry_id}", operation_id="updatePlanEntry")
def update_entry(
    plan: OwnedPlanDep,
    entry_id: str,
    body: PlanEntryPatch,
    session: SessionDep,
    _planner: PlannerDep,
) -> PlanEntryWithValidation:
    row = _entry(session, plan, entry_id)
    _check_portion(body.portion_factor)

    if body.module_id is not None:
        module = _module(session, body.module_id)
        _check_slot_fits(module, row.slot)
        day = session.get(models.PlanDay, row.plan_day_id)
        assert day is not None
        _check_single_main(session, day, row.slot, module, excluding=row.id)
        row.module_id = module.id
    if body.portion_factor is not None:
        row.portion_factor = body.portion_factor
    if body.position is not None:
        row.position = body.position

    session.flush()
    return _entry_with_validation(row, plan.id, session)


@router.delete("/plans/{plan_id}/entries/{entry_id}", operation_id="deletePlanEntry")
def delete_entry(
    plan: OwnedPlanDep, entry_id: str, session: SessionDep, _planner: PlannerDep
) -> ValidationReport:
    row = _entry(session, plan, entry_id)
    session.delete(row)
    session.flush()
    return _report(session, plan.id)
