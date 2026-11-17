"""The follower's two endpoints: rate a meal, and see today.

Both are shaped by the thirty-second budget (PRD §2.1). Today answers the whole
question in one request so no screen has to chain calls, and feedback takes one
request with one field.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from ration.api.broadcast import notify
from ration.api.deps import CurrentUserDep, OwnedPlanDep, SessionDep
from ration.api.errors import forbidden, not_found
from ration.api.schemas.follower import (
    FeedbackInput,
    FeedbackResponse,
    TodayEntry,
    TodaySlot,
    TodayView,
)
from ration.domain.nutrition import day_totals, entry_totals, totals_by_slot
from ration.domain.schedule import ordered_slots, slot_time
from ration.repositories import mappers, models
from ration.repositories.repositories import CatalogRepository, PlanRepository

router = APIRouter(tags=["follower"])


def _to_feedback(row: models.Feedback) -> FeedbackResponse:
    return FeedbackResponse(
        plan_entry_id=row.plan_entry_id,
        status=row.status,  # type: ignore[arg-type]
        rating=row.rating,  # type: ignore[arg-type]
        bloating=row.bloating,
        satiety=row.satiety,  # type: ignore[arg-type]
        note=row.note,
    )


@router.put("/plans/{plan_id}/entries/{entry_id}/feedback", operation_id="setFeedback")
def set_feedback(
    plan: OwnedPlanDep,
    entry_id: str,
    body: FeedbackInput,
    session: SessionDep,
    user: CurrentUserDep,
    request: Request = None,  # type: ignore[assignment]
) -> FeedbackResponse:
    """One request, one tap.

    `status` is inferred rather than submitted: the only data the real pilot
    produced was tried/not-tried and liked/disliked, and asking the follower to
    set both would be asking twice for one fact.
    """
    if user.is_planner:
        raise forbidden("Only the follower rates a meal")

    entry = session.scalars(
        select(models.PlanEntry)
        .join(models.PlanDay)
        .where(models.PlanEntry.id == entry_id, models.PlanDay.plan_id == plan.id)
    ).one_or_none()
    if entry is None:
        raise not_found("Entry")

    row = session.scalars(
        select(models.Feedback).where(models.Feedback.plan_entry_id == entry.id)
    ).one_or_none()
    if row is None:
        row = models.Feedback(plan_entry_id=entry.id)
        session.add(row)

    row.status = "tried"
    row.rating = body.rating
    if body.bloating is not None:
        row.bloating = body.bloating
    if body.satiety is not None:
        row.satiety = body.satiety
    if body.note is not None:
        row.note = body.note

    session.flush()
    notify(request, plan.id, ["feedback"])
    return _to_feedback(row)


@router.get("/today", operation_id="getToday")
def get_today(
    session: SessionDep,
    user: CurrentUserDep,
    date: Annotated[date_type | None, Query()] = None,
) -> TodayView:
    """Everything needed for today, in one request.

    Resolves the active plan rather than taking an id: the follower should not
    have to know which week they are in.
    """
    plan_row = session.scalars(
        select(models.Plan)
        .where(
            models.Plan.profile_id == user.profile_id,
            models.Plan.status == "active",
        )
        .order_by(models.Plan.start_date.desc())
    ).first()
    if plan_row is None:
        raise not_found("Active plan")

    wanted = date or date_type.today()
    day_row = next((d for d in plan_row.days if d.date == wanted), None)
    if day_row is None:
        raise not_found(f"Day {wanted.isoformat()} in the active plan")

    catalog = CatalogRepository(session).load()
    module_slugs = {i: s for s, i in CatalogRepository(session).module_ids_by_slug().items()}
    feedback = PlanRepository(session).feedback_for(plan_row.id)
    domain_day = mappers.plan_day_to_domain(day_row, module_slugs)
    per_slot = totals_by_slot(domain_day, catalog)
    totals = day_totals(domain_day, catalog)

    entries_by_slot: dict[str, list[TodayEntry]] = {}
    for entry_row in sorted(day_row.entries, key=lambda e: (e.slot, e.position)):
        slug = module_slugs[entry_row.module_id]
        module = catalog.module(slug)
        domain_entry = mappers.plan_entry_to_domain(entry_row, module_slugs)
        entry_totals_ = entry_totals(domain_entry, catalog)

        portion = (
            sum(
                (line.grams_cooked for line in module.lines),
                start=type(entry_row.portion_factor)(0),
            )
            * entry_row.portion_factor
        )

        # The unit follows the reader, like every other string that reaches
        # a screen. A note is still a formatted sentence built on the server,
        # which is the exception the domain layer is not allowed to make.
        grams = "g" if user.locale == "en" else "г"
        critical = [
            f"{catalog.ingredient(line.ingredient_id).name(user.locale)}: "
            f"{line.grams_cooked} {grams}"
            for line in module.lines
            if line.size_is_critical
        ]

        stored = feedback.get(entry_row.id)
        entries_by_slot.setdefault(entry_row.slot, []).append(
            TodayEntry(
                entry_id=entry_row.id,
                module_id=slug,
                module_name=module.name,
                portion_grams=portion,
                kcal=entry_totals_.kcal,
                protein_g=entry_totals_.protein_g,
                home_only="home_only" in module.tags,
                critical_notes=critical,
                feedback=(
                    FeedbackResponse(
                        plan_entry_id=entry_row.id,
                        status=stored.status,
                        rating=stored.rating,
                        bloating=stored.bloating,
                        satiety=stored.satiety,
                        note=stored.note,
                    )
                    if stored
                    else None
                ),
            )
        )

    return TodayView(
        plan_id=plan_row.id,
        date=day_row.date,
        day_index=day_row.day_index,
        day_template=day_row.day_template,  # type: ignore[arg-type]
        slots=[
            TodaySlot(
                slot=slot,
                time=slot_time(day_row.day_template, slot),  # type: ignore[arg-type]
                entries=entries_by_slot.get(slot, []),
                kcal=per_slot[slot].kcal if slot in per_slot else type(totals.kcal)(0),
                protein_g=(per_slot[slot].protein_g if slot in per_slot else type(totals.kcal)(0)),
            )
            for slot in ordered_slots()
        ],
        kcal=totals.kcal,
        protein_g=totals.protein_g,
    )
